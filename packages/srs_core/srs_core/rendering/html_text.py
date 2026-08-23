"""Converts Azure DevOps rich-text HTML fields to plain text for embedding
in a DOCX template.

This exists because docxtpl substitutes `{{ var }}` values directly into
the template's XML as text — it does not escape or validate them as HTML.
Real-world Azure descriptions are frequently not well-formed XML (unclosed
tags, bare `<`/`>`, stray `&`); inserting that raw markup corrupts the
document's XML from that point forward, and everything after it silently
vanishes when python-docx reopens it. `html.parser.HTMLParser` is used
specifically because it tolerates malformed markup instead of raising,
unlike an XML parser.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from xml.sax.saxutils import escape as _xml_escape

import markdown

_BLOCK_TAGS = {"div", "p", "li", "tr"}
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BREAK_TAGS = {"br"}
_HR_TAGS = {"hr"}
_FORMAT_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline"}
_WHITESPACE_RE = re.compile(r"\s+")

# -- Markdown detection --------------------------------------------------
#
# Some Azure DevOps custom fields (org-configured as plain-text, not
# rich-text HTML) are authored using Markdown syntax — headers, bold,
# pipe tables, horizontal rules — but the raw field value carries no
# format/type signal at all (the batch work-item API never returns field
# type metadata). html_to_blocks() below detects this heuristically and
# converts to HTML first so it flows through the same _BlockExtractor as
# genuine HTML fields.
#
# Deliberately two-tiered so a single stray `#` or `**` in an otherwise
# plain-prose field (e.g. a line that happens to start "# 4 is blocked
# because...") doesn't misclassify the whole field. A pipe-table
# separator row, a Setext heading underline, or a classic HR line don't
# occur by accident in plain prose and are trusted alone; a lone ATX
# heading, a lone bold pair, or a lone list marker need a second,
# independent signal to corroborate before the field is treated as
# Markdown. A genuine Markdown document (headings + bold + a table, say)
# clears this easily; an incidental character in plain prose does not.
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?>")

_MD_STRONG_SIGNALS = (
    re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", re.MULTILINE),  # pipe-table separator row
    re.compile(r"^\S.*\n(?:-{3,}|={3,})\s*$", re.MULTILINE),  # Setext heading underline
    re.compile(r"^(?:-{3,}|\*\s?\*\s?\*+|_{3,})\s*$", re.MULTILINE),  # classic "* * *" / "---" / "___" HR line
    re.compile(r"^```", re.MULTILINE),  # fenced code block marker - never occurs by accident in plain prose
)
_MD_WEAK_SIGNALS = (
    re.compile(r"^#{1,6}\s+\S", re.MULTILINE),  # ATX heading
    re.compile(r"\*\*\S[^\n]*?\S\*\*"),  # inline bold, same line only
    re.compile(r"^\s*[-*+]\s+\S", re.MULTILINE),  # unordered list marker
    re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE),  # ordered list marker
)


def _looks_like_markdown(text: str) -> bool:
    if _HTML_TAG_RE.search(text):
        return False
    if any(p.search(text) for p in _MD_STRONG_SIGNALS):
        return True
    return sum(1 for p in _MD_WEAK_SIGNALS if p.search(text)) >= 2


_LIST_ITEM_LINE_RE = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+\S")


def _fix_loose_list_boundary_bug(text: str) -> str:
    """Works around a real bug in Python-Markdown's list parser (verified
    directly against its HTML output, not guessed): a blank line between a
    list item's own text and an immediately-following, MORE-indented
    sub-list makes that item "loose" (<p>-wrapped) - and the parser then
    loses track of the outer list's boundary, silently swallowing the next
    several top-level sibling items into the nested sub-list instead of
    keeping them as siblings of the outer list.

    We don't render "loose" vs "tight" lists any differently, so the safe
    fix is to strip exactly that one blank line before handing text to the
    library - a purely structural (indentation-based) pattern match, not
    specific to any one document's wording, so it generalizes to any
    Markdown content with the same shape: item text, blank line, a more
    deeply indented sub-list line.
    """
    lines = text.split("\n")
    result = []
    last = len(lines) - 1
    for i, line in enumerate(lines):
        if line.strip() == "" and 0 < i < last:
            prev_match = _LIST_ITEM_LINE_RE.match(lines[i - 1])
            next_match = _LIST_ITEM_LINE_RE.match(lines[i + 1])
            if prev_match and next_match and len(next_match.group(1)) > len(prev_match.group(1)):
                continue  # drop this blank line - it's exactly what triggers the bug
        result.append(line)
    return "\n".join(result)


_TABLE_SEPARATOR_ROW_RE = _MD_STRONG_SIGNALS[0]  # the pipe-table separator row pattern, reused


def _fix_missing_blank_line_before_table(text: str) -> str:
    """Works around a real limitation in Python-Markdown's `tables`
    extension (verified directly against its HTML output, not guessed): a
    table must start its own block. A prose sentence immediately followed
    by a table header row, with no blank line between them, never gets
    recognized as a table at all — the whole thing (sentence + every pipe
    -delimited row) comes out as one flat paragraph, with the `|` syntax
    visible as literal text instead of a rendered table.

    A header row is unambiguously identified by the line right after it
    being a real separator row (`| --- | --- |`) — that pairing is exactly
    GFM/Python-Markdown table syntax, not a guess. If the line before it is
    non-blank and isn't itself a table row, insert the missing blank line.
    Purely structural, not specific to any one document's wording — any
    prose immediately followed by a table gets the same fix.
    """
    lines = text.split("\n")
    result: list[str] = []
    last = len(lines) - 1
    for i, line in enumerate(lines):
        is_header_row = "|" in line and i < last and _TABLE_SEPARATOR_ROW_RE.match(lines[i + 1])
        prev_line = result[-1] if result else ""
        if is_header_row and prev_line.strip() != "" and "|" not in prev_line:
            result.append("")  # insert the missing blank line the table needs to be recognized
        result.append(line)
    return "\n".join(result)


class _PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS or tag in _BREAK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def html_to_plain_text(html: str | None) -> str | None:
    if not html:
        return None
    parser = _PlainTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text() or None


class _BlockExtractor(HTMLParser):
    """Unlike `_PlainTextExtractor`, this keeps structure intact instead of
    flattening every tag to a newline:

    - `<table>`/`<ul>`/`<ol>` become `table`/`list` blocks instead of being
      flattened to plain text. Real Azure DevOps custom fields (Data
      Dictionary, Requirement Analysis, ...) routinely author actual
      `<table>` markup — flattening that to plain text turned each row into
      a sparse few-word paragraph, which the org template's "S Notes" style
      (justified, meant for genuine prose) then stretched into unreadable,
      widely-spaced text.
    - Inline formatting (`<b>`/`<strong>`, `<i>`/`<em>`, `<u>`) is preserved
      as per-run `bold`/`italic`/`underline` flags instead of being
      silently discarded — a work item's "Short CIF" / "Full CIF" bolded
      inline in its description used to render as plain, unstyled text.

    Every text-bearing block (`text`, list items, table cells) is a list of
    runs — `{"text": ..., "bold": bool, "italic": bool, "underline": bool}`
    — mirroring how a docx paragraph is actually built from runs, so the
    renderer can apply each run's formatting directly with no re-parsing.

    Never raises on malformed markup, same tolerance as `html_to_plain_text`
    — a table left unclosed at EOF, for example, still emits whatever rows
    were captured rather than losing the content or crashing generation.
    """

    def __init__(self, *, headings_as_blocks: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self._blocks: list[dict] = []

        # Run-accumulation state for whichever text-bearing context is
        # currently active (top-level paragraph / list item / table cell —
        # only one is ever in progress at once for this HTML shape).
        self._current_runs: list[dict] = []
        self._run_buffer: list[str] = []
        self._format_counts = {"bold": 0, "italic": 0, "underline": 0, "mono": 0}

        # A fenced ```code``` block (<pre><code>...) - content is captured
        # verbatim in _code_buffer, bypassing the normal run-buffer path,
        # since code needs its exact whitespace/line breaks preserved
        # instead of collapsed like prose.
        self._in_pre = False
        self._code_buffer: list[str] = []
        self._code_language: str | None = None

        # Genuine Azure HTML fields already use <h1>-<h6> for things other
        # than document-style headings — e.g. a <h3>Context Diagram</h3>
        # right before its own <img> is deliberately matched as that
        # image's caption (see _render_blocks in docx_builder.py), which
        # relies on the heading landing in the same "text" block type as
        # everything else. Only content that arrived here via Markdown
        # conversion (see html_to_blocks) gets real "heading" blocks — a
        # Markdown document's headings never carry that caption meaning.
        self._headings_as_blocks = headings_as_blocks

        # Set by a top-level <h1>-<h6> start tag (when _headings_as_blocks),
        # consumed by the very next _flush_paragraph() (its own end tag, or
        # whatever closes it next on malformed markup) so that one
        # paragraph becomes a "heading" block instead of a "text" block.
        self._pending_heading_level: int | None = None

        self._in_table = False
        self._table_rows: list[list[list[dict]]] = []
        self._current_row: list[list[dict]] | None = None
        self._in_cell = False

        # A stack, not a single flat state, because a <ul>/<ol> can be
        # nested inside an <li> of an outer list (e.g. a numbered outline
        # with an indented bullet sub-list under one item) - arbitrarily
        # deep, not just one level. Each frame: {"ordered": bool, "items":
        # [{"runs": [...], "sublist": <list-block-or-None>}, ...]}. When a
        # nested list closes, its block gets attached as the "sublist" of
        # whichever item of the PARENT frame was open when it started.
        self._list_stack: list[dict] = []
        self._in_item = False
        # True once the currently-open <li> has already had an item
        # appended to its parent frame because a nested list started inside
        # it - so the matching </li> doesn't append a duplicate empty item.
        self._li_item_already_appended = False

    # -- run/paragraph accumulation ---------------------------------------

    def _current_format(self) -> dict:
        return {name: count > 0 for name, count in self._format_counts.items()}

    def _flush_run(self) -> None:
        if not self._run_buffer:
            return
        # Collapses internal whitespace/newlines (real Azure HTML is often
        # pretty-printed) to a single space WITHOUT stripping a leading or
        # trailing one — that single space is frequently the only word
        # separator between this run and its neighbor, e.g. a bold "Short
        # CIF" run sitting between two plain-text runs.
        text = _WHITESPACE_RE.sub(" ", "".join(self._run_buffer))
        self._run_buffer = []
        if text:
            self._current_runs.append({"text": text, **self._current_format()})

    def _take_runs(self) -> list[dict]:
        """Flushes the pending run and trims only the OUTER whitespace edges
        of the whole paragraph/item/cell (first run's leading, last run's
        trailing) — never the space between runs.
        """
        self._flush_run()
        runs = self._current_runs
        self._current_runs = []
        if not runs:
            return []
        runs = [dict(r) for r in runs]
        runs[0]["text"] = runs[0]["text"].lstrip()
        runs[-1]["text"] = runs[-1]["text"].rstrip()
        return [r for r in runs if r["text"]]

    def _flush_paragraph(self) -> None:
        runs = self._take_runs()
        level = self._pending_heading_level
        self._pending_heading_level = None
        if runs:
            if level is not None:
                self._blocks.append({"type": "heading", "level": level, "runs": runs})
            else:
                self._blocks.append({"type": "text", "runs": runs})

    def _block_boundary(self) -> None:
        """A block-tag boundary (`<p>`, `<div>`, `<h1>`, ...) or `<br>`.
        Inside a table cell or list item this only segments the run buffer
        (the cell/item itself isn't over yet); everywhere else it ends the
        current top-level paragraph.
        """
        if self._in_cell or self._in_item:
            self._flush_run()
        else:
            self._flush_paragraph()

    # -- table -------------------------------------------------------------

    def _flush_table(self) -> None:
        self._in_table = False
        if self._in_cell:
            self._current_row = self._current_row if self._current_row is not None else []
            self._current_row.append(self._take_runs())
            self._in_cell = False
        if self._current_row is not None:
            self._table_rows.append(self._current_row)
            self._current_row = None
        if self._table_rows:
            self._blocks.append({"type": "table", "rows": self._table_rows})
        self._table_rows = []

    # -- list ----------------------------------------------------------

    def _pop_list_frame(self) -> dict | None:
        frame = self._list_stack.pop()
        if not frame["items"]:
            return None
        return {"type": "list", "ordered": frame["ordered"], "items": frame["items"]}

    def _close_list(self) -> None:
        """Pops the innermost list frame. If it was nested inside another
        list's <li>, attaches it as that item's "sublist" instead of
        emitting it as its own top-level block.
        """
        list_block = self._pop_list_frame()
        if self._list_stack:
            parent_items = self._list_stack[-1]["items"]
            if parent_items and list_block is not None:
                parent_items[-1]["sublist"] = list_block
        elif list_block is not None:
            self._blocks.append(list_block)

    # -- HTMLParser callbacks ----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _FORMAT_TAGS:
            # Flush BEFORE changing the format counters — otherwise text
            # before and after this tag both end up in the same run buffer
            # and get flushed together under whichever formatting happened
            # to be active when the run finally closes, discarding the
            # formatting change entirely.
            self._flush_run()
            self._format_counts[_FORMAT_TAGS[tag]] += 1
        elif tag == "table":
            self._flush_paragraph()
            self._in_table = True
            self._table_rows = []
        elif tag == "tr" and self._in_table:
            self._current_row = []
        elif tag in ("td", "th") and self._in_table:
            self._in_cell = True
            self._current_runs = []
        elif tag in ("ul", "ol") and not self._in_table:
            if self._list_stack and self._in_item:
                # Nested inside the currently-open <li> - that item's own
                # direct text (if any) is captured now as its "runs"; the
                # nested list's block gets attached to this same item as
                # "sublist" once its closing tag is hit (_close_list).
                runs = self._take_runs()
                self._list_stack[-1]["items"].append({"runs": runs, "sublist": None})
                self._li_item_already_appended = True
            elif not self._list_stack:
                self._flush_paragraph()
            self._list_stack.append({"ordered": tag == "ol", "items": []})
        elif tag == "li" and self._list_stack:
            self._in_item = True
            self._li_item_already_appended = False
            self._current_runs = []
        elif tag == "img" and not self._in_table and not self._list_stack:
            # Emitted in-place, not batched separately — this is what lets
            # the renderer put each diagram where it actually belongs (right
            # after its own heading, e.g. Azure's "Context Diagram" /
            # "Container Diagram" sections) instead of dumping every image
            # for a work item at the end with no idea which was which.
            self._flush_paragraph()
            src = next((value for name, value in attrs if name == "src" and value), None)
            if src:
                self._blocks.append({"type": "image", "src": src})
        elif tag == "pre":
            self._flush_paragraph()
            self._in_pre = True
            self._code_buffer = []
            self._code_language = None
        elif tag == "code":
            if self._in_pre:
                # fenced_code emits class="language-sql" when a language
                # hint follows the opening ``` - fall back gracefully to a
                # bare class name in case that ever changes.
                cls = next((value for name, value in attrs if name == "class" and value), None)
                if cls:
                    self._code_language = cls[len("language-") :] if cls.startswith("language-") else cls
            else:
                # An inline `code span` (single backticks), not a fenced block.
                self._flush_run()
                self._format_counts["mono"] += 1
        elif tag in _BREAK_TAGS:
            self._block_boundary()
        elif tag in _HR_TAGS:
            self._block_boundary()
        elif tag in _HEADING_TAGS:
            if self._headings_as_blocks and not (self._in_cell or self._in_item):
                self._flush_paragraph()
                self._pending_heading_level = _HEADING_TAGS[tag]
            else:
                self._block_boundary()
        elif tag in _BLOCK_TAGS:
            self._block_boundary()

    def handle_endtag(self, tag: str) -> None:
        if tag in _FORMAT_TAGS:
            self._flush_run()  # same reason as in handle_starttag — flush before the format changes back
            name = _FORMAT_TAGS[tag]
            if self._format_counts[name] > 0:
                self._format_counts[name] -= 1
        elif tag == "table":
            self._flush_table()
        elif tag == "tr" and self._in_table:
            if self._current_row is not None:
                self._table_rows.append(self._current_row)
            self._current_row = None
        elif tag in ("td", "th") and self._in_table:
            cell_runs = self._take_runs()
            if self._current_row is not None:
                self._current_row.append(cell_runs)
            self._in_cell = False
        elif tag in ("ul", "ol") and self._list_stack:
            self._close_list()
        elif tag == "li" and self._list_stack:
            if self._li_item_already_appended:
                # Any trailing text after the nested sublist (rare, but not
                # invalid markup) extends that same item's runs rather than
                # starting a new sibling item.
                trailing_runs = self._take_runs()
                if trailing_runs:
                    self._list_stack[-1]["items"][-1]["runs"].extend(trailing_runs)
            else:
                item_runs = self._take_runs()
                if item_runs:
                    self._list_stack[-1]["items"].append({"runs": item_runs, "sublist": None})
            self._in_item = False
            self._li_item_already_appended = False
        elif tag == "pre":
            text = "".join(self._code_buffer).strip("\n")
            if text:
                self._blocks.append({"type": "code", "text": text, "language": self._code_language})
            self._in_pre = False
            self._code_buffer = []
            self._code_language = None
        elif tag == "code":
            if not self._in_pre:
                self._flush_run()
                if self._format_counts["mono"] > 0:
                    self._format_counts["mono"] -= 1
        elif tag in _HEADING_TAGS:
            if self._headings_as_blocks and not (self._in_cell or self._in_item):
                self._flush_paragraph()
            else:
                self._block_boundary()
        elif tag in _BLOCK_TAGS:
            self._block_boundary()

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._code_buffer.append(data)
        else:
            self._run_buffer.append(data)

    def blocks(self) -> list[dict]:
        # EOF cleanup — malformed markup can leave any of these open.
        if self._in_pre:
            text = "".join(self._code_buffer).strip("\n")
            if text:
                self._blocks.append({"type": "code", "text": text, "language": self._code_language})
            self._in_pre = False
        if self._in_table:
            self._flush_table()
        while self._list_stack:
            self._close_list()
        self._flush_paragraph()
        return self._blocks


_NBSP_ENTITY_RE = re.compile(r"&(?:nbsp|#160|#x0*a0);", re.IGNORECASE)


def _normalize_nbsp_artifacts(text: str) -> str:
    """Real Azure DevOps field content sometimes carries literal
    non-breaking-space HTML entities (`&nbsp;`, `&#160;`, `&#xA0;`) as
    plain text - a common copy/paste artifact from pasting HTML-formatted
    content (a Word table, a web page) into a plain-text/Markdown field.
    Left alone, these round-trip faithfully through Markdown's own
    HTML-escaping of fenced code blocks (a literal `&` becomes `&amp;` on
    the way in, which our parser correctly decodes back to `&` on the way
    out) and come out the other end as literal "&nbsp;" text sitting in
    the middle of a table/DDL block, instead of the whitespace they were
    always meant to represent. Also normalizes an already-decoded U+00A0
    character for the same reason - same artifact, different form.
    """
    return _NBSP_ENTITY_RE.sub(" ", text).replace("\xa0", " ")


def html_to_blocks(html: str | None) -> list[dict]:
    """Structured alternative to `html_to_plain_text` — returns a list of
    blocks in source order, JSON-safe for travel through the Celery chain
    payload:
    `{"type": "text", "runs": [{"text": ..., "bold": ..., "italic": ..., "underline": ..., "mono": ...}, ...]}`
    `{"type": "heading", "level": 1-6, "runs": [...]}`
    `{"type": "code", "text": "...", "language": "sql" | None}`
    `{"type": "list", "ordered": bool, "items": [{"runs": [...], "sublist": <list-block-or-None>}, ...]}`
    `{"type": "table", "rows": [[<run list>, ...], ...]}`
    Empty/None input returns an empty list.

    Some Azure DevOps custom fields carry Markdown source instead of HTML
    (see the module-level comment above `_looks_like_markdown`) — those are
    converted to HTML first so they flow through the same parser as
    genuinely-HTML fields; real HTML and plain prose are both passed
    through unchanged.
    """
    if not html:
        return []
    html = _normalize_nbsp_artifacts(html)
    is_markdown = _looks_like_markdown(html)
    if is_markdown:
        preprocessed = _fix_missing_blank_line_before_table(_fix_loose_list_boundary_bug(html))
        html = markdown.markdown(preprocessed, extensions=["tables", "fenced_code"])
    parser = _BlockExtractor(headings_as_blocks=is_markdown)
    parser.feed(html)
    parser.close()
    return parser.blocks()


def _runs_to_text(runs: list[dict]) -> str:
    return "".join(r["text"] for r in runs)


def _list_items_to_lines(items: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.append(_runs_to_text(item.get("runs") or []))
        sublist = item.get("sublist")
        if sublist:
            lines.extend(_list_items_to_lines(sublist.get("items") or []))
    return lines


def blocks_to_plain_text(blocks: list[dict]) -> str:
    """Flattens `html_to_blocks` output back to a plain-text snippet — used
    where layout/formatting doesn't matter (e.g. grounding an LLM prompt),
    not for rendering. Table rows join cells with " | "; list items (and
    any nested sub-items) go one per line; code blocks contribute their
    raw text as-is.
    """
    parts: list[str] = []
    for block in blocks:
        if block["type"] in ("text", "heading"):
            parts.append(_runs_to_text(block["runs"]))
        elif block["type"] == "code":
            parts.append(block.get("text") or "")
        elif block["type"] == "list":
            parts.extend(_list_items_to_lines(block.get("items") or []))
        elif block["type"] == "table":
            parts.extend(" | ".join(_runs_to_text(cell) for cell in row) for row in block["rows"])
    return "\n".join(p for p in parts if p)


def docxtpl_safe_text(value: str | None) -> str | None:
    """XML-escapes a plain-text string for direct `{{ var }}` substitution
    into a docxtpl template.

    docxtpl performs NO escaping of its own on substituted values — it
    inserts them as-is into the template's XML text. A stray, unbalanced
    `<` or `>` (e.g. from a decoded HTML entity like `&lt;`, or literal
    text a user typed) silently corrupts the document's XML from that
    point forward; everything after it vanishes when reopened. This must
    be applied to every user-controlled string passed to docxtpl, not just
    HTML-derived ones.
    """
    if value is None:
        return None
    return _xml_escape(value)
