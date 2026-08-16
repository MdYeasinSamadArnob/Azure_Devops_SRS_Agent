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

_BLOCK_TAGS = {"div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
_BREAK_TAGS = {"br"}
_FORMAT_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline"}
_WHITESPACE_RE = re.compile(r"\s+")


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

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocks: list[dict] = []

        # Run-accumulation state for whichever text-bearing context is
        # currently active (top-level paragraph / list item / table cell —
        # only one is ever in progress at once for this HTML shape).
        self._current_runs: list[dict] = []
        self._run_buffer: list[str] = []
        self._format_counts = {"bold": 0, "italic": 0, "underline": 0}

        self._in_table = False
        self._table_rows: list[list[list[dict]]] = []
        self._current_row: list[list[dict]] | None = None
        self._in_cell = False

        self._in_list = False
        self._list_items: list[list[dict]] = []
        self._in_item = False

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
        if runs:
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

    def _flush_list(self) -> None:
        self._in_list = False
        if self._in_item:
            item_runs = self._take_runs()
            if item_runs:
                self._list_items.append(item_runs)
            self._in_item = False
        if self._list_items:
            self._blocks.append({"type": "list", "items": self._list_items})
        self._list_items = []

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
            self._flush_paragraph()
            self._in_list = True
            self._list_items = []
        elif tag == "li" and self._in_list:
            self._in_item = True
            self._current_runs = []
        elif tag == "img" and not self._in_table and not self._in_list:
            # Emitted in-place, not batched separately — this is what lets
            # the renderer put each diagram where it actually belongs (right
            # after its own heading, e.g. Azure's "Context Diagram" /
            # "Container Diagram" sections) instead of dumping every image
            # for a work item at the end with no idea which was which.
            self._flush_paragraph()
            src = next((value for name, value in attrs if name == "src" and value), None)
            if src:
                self._blocks.append({"type": "image", "src": src})
        elif tag in _BREAK_TAGS:
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
        elif tag in ("ul", "ol") and self._in_list:
            self._flush_list()
        elif tag == "li" and self._in_list:
            item_runs = self._take_runs()
            if item_runs:
                self._list_items.append(item_runs)
            self._in_item = False
        elif tag in _BLOCK_TAGS:
            self._block_boundary()

    def handle_data(self, data: str) -> None:
        self._run_buffer.append(data)

    def blocks(self) -> list[dict]:
        # EOF cleanup — malformed markup can leave any of these open.
        if self._in_table:
            self._flush_table()
        if self._in_list:
            self._flush_list()
        self._flush_paragraph()
        return self._blocks


def html_to_blocks(html: str | None) -> list[dict]:
    """Structured alternative to `html_to_plain_text` — returns a list of
    blocks in source order, JSON-safe for travel through the Celery chain
    payload:
    `{"type": "text", "runs": [{"text": ..., "bold": ..., "italic": ..., "underline": ...}, ...]}`
    `{"type": "list", "items": [<run list>, ...]}`
    `{"type": "table", "rows": [[<run list>, ...], ...]}`
    Empty/None input returns an empty list.
    """
    if not html:
        return []
    parser = _BlockExtractor()
    parser.feed(html)
    parser.close()
    return parser.blocks()


def _runs_to_text(runs: list[dict]) -> str:
    return "".join(r["text"] for r in runs)


def blocks_to_plain_text(blocks: list[dict]) -> str:
    """Flattens `html_to_blocks` output back to a plain-text snippet — used
    where layout/formatting doesn't matter (e.g. grounding an LLM prompt),
    not for rendering. Table rows join cells with " | "; list items go one
    per line.
    """
    parts: list[str] = []
    for block in blocks:
        if block["type"] == "text":
            parts.append(_runs_to_text(block["runs"]))
        elif block["type"] == "list":
            parts.extend(_runs_to_text(item) for item in block["items"])
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
