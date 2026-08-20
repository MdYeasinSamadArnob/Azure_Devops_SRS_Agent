from srs_core.rendering.html_text import blocks_to_plain_text, docxtpl_safe_text, html_to_blocks, html_to_plain_text


def test_strips_tags_and_preserves_text():
    html = "<div>Hello <b>world</b></div>"
    assert html_to_plain_text(html) == "Hello world"


def test_unescapes_entities():
    html = "<span>stdocdtl--&gt;stamlxml &amp; stuff</span>"
    assert html_to_plain_text(html) == "stdocdtl-->stamlxml & stuff"


def test_handles_malformed_unclosed_tags_without_raising():
    # Real Azure DevOps rich-text fields are frequently not well-formed XML.
    html = "<div>text with <unclosed tag content"
    result = html_to_plain_text(html)
    assert result is not None
    assert "text with" in result


def test_none_and_empty_return_none():
    assert html_to_plain_text(None) is None
    assert html_to_plain_text("") is None


def test_docxtpl_safe_text_escapes_angle_brackets_and_ampersand():
    # This is the actual corruption vector: docxtpl inserts {{ var }}
    # substitutions into the template XML with zero escaping of its own.
    assert docxtpl_safe_text("a < b > c & d") == "a &lt; b &gt; c &amp; d"


def test_docxtpl_safe_text_passthrough_for_none():
    assert docxtpl_safe_text(None) is None


def _plain(text: str) -> dict:
    return {"text": text, "bold": False, "italic": False, "underline": False, "mono": False}


def _bold(text: str) -> dict:
    return {"text": text, "bold": True, "italic": False, "underline": False, "mono": False}


def _item(*run_dicts: dict, sublist: dict | None = None) -> dict:
    return {"runs": list(run_dicts), "sublist": sublist}


def _run_texts(runs: list[dict]) -> list[str]:
    return [r["text"] for r in runs]


def test_html_to_blocks_parses_a_table_into_rows_and_cells():
    """Regression test for a real reported bug: real Azure DevOps custom
    fields (Data Dictionary especially) are genuinely authored as HTML
    tables — flattening them to plain text turned each row into a sparse
    few-word paragraph, unreadable once the org template's justified style
    stretched it. Tables must come through as structured rows, not text.
    """
    html = (
        "<table><tr><th>Field</th><th>Type</th></tr>"
        "<tr><td>customer_id</td><td>UUID</td></tr>"
        "<tr><td>kyc_status</td><td>ENUM</td></tr></table>"
    )
    blocks = html_to_blocks(html)
    assert blocks == [
        {
            "type": "table",
            "rows": [
                [[_plain("Field")], [_plain("Type")]],
                [[_plain("customer_id")], [_plain("UUID")]],
                [[_plain("kyc_status")], [_plain("ENUM")]],
            ],
        }
    ]


def test_html_to_blocks_parses_a_list_into_items():
    html = "<ul><li>Only admins may approve.</li><li>Every change is logged.</li></ul>"
    blocks = html_to_blocks(html)
    assert blocks == [
        {
            "type": "list",
            "ordered": False,
            "items": [
                _item(_plain("Only admins may approve.")),
                _item(_plain("Every change is logged.")),
            ],
        }
    ]


def test_html_to_blocks_mixes_text_list_and_table_in_source_order():
    html = "<p>Intro paragraph.</p><ul><li>Point one</li></ul><table><tr><td>A</td><td>B</td></tr></table><p>Outro.</p>"
    blocks = html_to_blocks(html)
    assert [b["type"] for b in blocks] == ["text", "list", "table", "text"]
    assert _run_texts(blocks[0]["runs"]) == ["Intro paragraph."]
    assert _run_texts(blocks[3]["runs"]) == ["Outro."]


def test_html_to_blocks_collapses_whitespace_inside_cells():
    # Real Azure HTML is often pretty-printed with newlines/indentation
    # between and inside tags — without collapsing, that whitespace was
    # exactly what stretched flattened table rows into ugly spaced-out text.
    html = "<table><tr>\n  <td>\n    customer_id\n  </td>\n  <td>UUID</td>\n</tr></table>"
    blocks = html_to_blocks(html)
    assert blocks == [{"type": "table", "rows": [[[_plain("customer_id")], [_plain("UUID")]]]}]


def test_html_to_blocks_survives_an_unclosed_table():
    # Real Azure DevOps rich-text fields are frequently not well-formed —
    # must still capture whatever rows were parsed, not raise or lose them.
    html = "<table><tr><td>A</td><td>B</td></tr>"
    blocks = html_to_blocks(html)  # must not raise
    assert blocks == [{"type": "table", "rows": [[[_plain("A")], [_plain("B")]]]}]


def test_html_to_blocks_none_and_empty_return_empty_list():
    assert html_to_blocks(None) == []
    assert html_to_blocks("") == []


def test_html_to_blocks_plain_prose_still_works_like_before():
    html = "<div>Hello <b>world</b></div>"
    blocks = html_to_blocks(html)
    assert blocks == [{"type": "text", "runs": [_plain("Hello "), _bold("world")]}]


def test_html_to_blocks_preserves_bold_italic_underline_as_run_flags():
    """Regression test for a real reported bug: a work item's inline bold
    text (e.g. "the **Short CIF** or **Full CIF** onboarding process") was
    silently discarded — everything rendered as plain, unstyled text.
    """
    html = "Enable login via <b>Short CIF</b> or <strong>Full CIF</strong>, with <i>optional</i> <u>biometric</u> auth."
    blocks = html_to_blocks(html)
    assert len(blocks) == 1
    runs = blocks[0]["runs"]
    by_text = {r["text"].strip(): r for r in runs}
    assert by_text["Short CIF"]["bold"] is True
    assert by_text["Full CIF"]["bold"] is True
    assert by_text["optional"]["italic"] is True
    assert by_text["biometric"]["underline"] is True
    assert by_text["Enable login via"]["bold"] is False


def test_html_to_blocks_preserves_bold_within_list_items():
    html = "<ul><li>Only <b>admins</b> may approve.</li></ul>"
    blocks = html_to_blocks(html)
    item_runs = blocks[0]["items"][0]["runs"]
    assert any(r["bold"] and r["text"].strip() == "admins" for r in item_runs)
    assert any(not r["bold"] and "Only" in r["text"] for r in item_runs)


def test_html_to_blocks_nested_formatting_survives_unwind():
    # <b>bold <i>bold-italic</i> bold again</b> plain
    html = "<b>bold <i>bold-italic</i> bold again</b> plain"
    blocks = html_to_blocks(html)
    runs = blocks[0]["runs"]
    by_text = {r["text"].strip(): r for r in runs}
    assert by_text["bold-italic"]["bold"] is True
    assert by_text["bold-italic"]["italic"] is True
    assert by_text["plain"]["bold"] is False


def test_html_to_blocks_emits_an_image_block_at_its_position():
    """Regression test for a real reported bug: embedded diagrams (Context
    Diagram, Container Diagram, ...) rendered as anonymous pictures with no
    title and no relation to their surrounding content, because images were
    extracted completely separately from the text and just batched at the
    end. An <img> must come through as its own block, in place, so the
    renderer can put it right where it actually belongs.
    """
    html = "<h3>Context Diagram</h3><img src='https://dev.azure.com/org/proj/_apis/wit/attachments/abc.png'/><p>Next section.</p>"
    blocks = html_to_blocks(html)
    assert [b["type"] for b in blocks] == ["text", "image", "text"]
    assert blocks[1]["src"] == "https://dev.azure.com/org/proj/_apis/wit/attachments/abc.png"
    assert _run_texts(blocks[0]["runs"]) == ["Context Diagram"]
    assert _run_texts(blocks[2]["runs"]) == ["Next section."]


def test_html_to_blocks_multiple_images_preserve_order_and_captions():
    html = (
        "<h3>Context Diagram</h3><img src='ctx.png'/>"
        "<h3>Container Diagram</h3><img src='container.png'/>"
        "<h3>Deployment Diagram</h3><img src='deploy.png'/>"
    )
    blocks = html_to_blocks(html)
    image_srcs = [b["src"] for b in blocks if b["type"] == "image"]
    assert image_srcs == ["ctx.png", "container.png", "deploy.png"]
    captions = [_run_texts(b["runs"])[0] for b in blocks if b["type"] == "text"]
    assert captions == ["Context Diagram", "Container Diagram", "Deployment Diagram"]


def test_html_to_blocks_image_without_src_is_skipped():
    html = "<p>Before</p><img alt='no source'/><p>After</p>"
    blocks = html_to_blocks(html)
    assert [b["type"] for b in blocks] == ["text", "text"]


def test_blocks_to_plain_text_skips_image_blocks_without_crashing():
    blocks = [{"type": "text", "runs": [_plain("Before.")]}, {"type": "image", "src": "x.png"}, {"type": "text", "runs": [_plain("After.")]}]
    assert blocks_to_plain_text(blocks) == "Before.\nAfter."


def test_blocks_to_plain_text_flattens_every_block_type():
    blocks = [
        {"type": "text", "runs": [_plain("Intro.")]},
        {"type": "list", "ordered": False, "items": [_item(_plain("one")), _item(_plain("two"))]},
        {"type": "table", "rows": [[[_plain("a")], [_plain("b")]], [[_plain("c")], [_plain("d")]]]},
        {"type": "code", "text": "SELECT 1;", "language": "sql"},
    ]
    flat = blocks_to_plain_text(blocks)
    assert flat == "Intro.\none\ntwo\na | b\nc | d\nSELECT 1;"


def test_blocks_to_plain_text_empty_list_returns_empty_string():
    assert blocks_to_plain_text([]) == ""


def test_blocks_to_plain_text_includes_heading_text():
    blocks = [{"type": "heading", "level": 2, "runs": [_plain("Overview")]}, {"type": "text", "runs": [_plain("Body.")]}]
    assert blocks_to_plain_text(blocks) == "Overview\nBody."


# -- Markdown-formatted custom fields ------------------------------------
#
# Regression coverage for a real reported bug: a custom Azure DevOps field
# (e.g. "Data Dictionary") authored in Markdown, not HTML, rendered in the
# generated DOCX as one wall of raw '#'/'**'/'* * *'/'|' characters instead
# of real headings/bold/tables — html_to_blocks had zero Markdown awareness
# and HTMLParser doesn't react to any of that syntax.


def test_html_to_blocks_converts_a_genuine_markdown_field_into_real_blocks():
    md = (
        "# Title\n\n"
        "**Database:** PostgreSQL 16+\n\n"
        "* * *\n\n"
        "Overview\n--------\n\n"
        "It **does not store business data** from customer databases.\n\n"
        "| Symbol | Meaning |\n"
        "| --- | --- |\n"
        "| PK | Primary Key |\n"
    )
    blocks = html_to_blocks(md)
    types = [b["type"] for b in blocks]
    assert types.count("heading") >= 2  # ATX "# Title" and Setext "Overview\n---"
    assert "table" in types

    title_block = next(b for b in blocks if b["type"] == "heading")
    assert _run_texts(title_block["runs"]) == ["Title"]
    assert title_block["level"] == 1

    intro_block = next(b for b in blocks if b["type"] == "text" and "Database:" in _run_texts(b["runs"])[0])
    assert any(r["bold"] and r["text"].strip() == "Database:" for r in intro_block["runs"])

    body_block = next(b for b in blocks if b["type"] == "text" and any("does not store" in t for t in _run_texts(b["runs"])))
    assert any(r["bold"] and "does not store business data" in r["text"] for r in body_block["runs"])

    table_block = next(b for b in blocks if b["type"] == "table")
    header_texts = [_run_texts(cell) for cell in table_block["rows"][0]]
    assert header_texts == [["Symbol"], ["Meaning"]]
    assert any(_run_texts(cell) == ["PK"] for row in table_block["rows"] for cell in row)

    # No literal Markdown syntax characters survive anywhere in the output.
    flat = blocks_to_plain_text(blocks)
    assert "#" not in flat
    assert "**" not in flat
    assert "* * *" not in flat


def test_html_to_blocks_does_not_convert_a_lone_stray_hash_in_plain_prose():
    """The false-positive guard: a single weak signal (one ATX-heading-like
    line) alone must NOT flip an ordinary sentence into Markdown mode.
    """
    text = "# 4 is blocked because the upstream service is down."
    blocks = html_to_blocks(text)
    assert [b["type"] for b in blocks] == ["text"]
    assert _run_texts(blocks[0]["runs"])[0].startswith("#")


def test_html_to_blocks_does_not_convert_a_lone_bold_pair_in_plain_prose():
    text = "Please review this **before** the end of day."
    blocks = html_to_blocks(text)
    assert [b["type"] for b in blocks] == ["text"]
    assert "**before**" in _run_texts(blocks[0]["runs"])[0]


def test_html_to_blocks_converts_when_two_weak_signals_corroborate():
    # No strong signal (no table/setext/hr) — but a heading and bold
    # together are enough independent signals to treat this as genuine
    # Markdown, not an accidental character in plain prose.
    text = "# Notice\n\nThis is **important** information for the team."
    blocks = html_to_blocks(text)
    heading = next(b for b in blocks if b["type"] == "heading")
    assert _run_texts(heading["runs"]) == ["Notice"]


def test_html_to_blocks_prioritizes_real_html_tags_over_markdown_look_alikes():
    # Real HTML always wins — Markdown-conversion is never even considered
    # once an actual tag is present, regardless of what the text inside it
    # happens to look like.
    html = "<p>Section # 4 has <b>**not**</b> been reviewed.</p>"
    blocks = html_to_blocks(html)
    assert blocks[0]["type"] == "text"
    assert any(r["bold"] and r["text"] == "**not**" for r in blocks[0]["runs"])


def test_html_to_blocks_h3_caption_before_image_still_works_for_real_html():
    """Genuine Azure HTML already uses <h3> for diagram captions (e.g.
    "Context Diagram" right above its own <img>) — that must keep landing
    in a "text" block, not a "heading" block, since the caption-matching
    logic in docx_builder.py's _render_blocks only looks for "text".
    Markdown-only content gets real "heading" blocks; real HTML doesn't.
    """
    html = "<h3>Context Diagram</h3><img src='ctx.png'/>"
    blocks = html_to_blocks(html)
    assert blocks[0]["type"] == "text"
    assert _run_texts(blocks[0]["runs"]) == ["Context Diagram"]


# -- Fenced code blocks ---------------------------------------------------
#
# Regression coverage for a real reported bug: a custom field with a
# ```sql ... ``` fenced code block rendered as literal backtick/language-tag
# text instead of a distinct, formatted code block — the Markdown-to-HTML
# conversion never enabled the fenced_code extension, and even once it did,
# _BlockExtractor had no handling for <pre>/<code> at all.


def test_html_to_blocks_parses_a_fenced_code_block():
    md = "Some intro.\n\n```sql\nCREATE EXTENSION IF NOT EXISTS pgcrypto;\n```\n\nMore text."
    blocks = html_to_blocks(md)
    code_block = next(b for b in blocks if b["type"] == "code")
    assert code_block["text"] == "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
    assert code_block["language"] == "sql"
    # No literal fence markers or language tag survive as visible text elsewhere.
    flat = blocks_to_plain_text(blocks)
    assert "```" not in flat
    assert "language-sql" not in flat


def test_html_to_blocks_preserves_multiline_code_exactly():
    md = "```sql\nSELECT 1;\n\nSELECT 2;\n```"
    blocks = html_to_blocks(md)
    code_block = next(b for b in blocks if b["type"] == "code")
    assert code_block["text"] == "SELECT 1;\n\nSELECT 2;"


def test_html_to_blocks_marks_inline_code_spans_as_mono_not_fenced():
    # Two corroborating signals (heading + bold) so this is unambiguously
    # treated as Markdown — inline-code-span syntax alone isn't one of the
    # detection signals, so it needs the rest of the field to qualify.
    md = "# Notice\n\nRun `SELECT 1;` to check the connection. This is **important**."
    blocks = html_to_blocks(md)
    assert not any(b["type"] == "code" for b in blocks)  # a single-backtick span isn't a fenced block
    text_block = next(b for b in blocks if b["type"] == "text")
    assert any(r["mono"] and r["text"] == "SELECT 1;" for r in text_block["runs"])


# -- Nested lists -----------------------------------------------------------
#
# Regression coverage for a real reported bug: a numbered outline with an
# indented bullet sub-list under one item (e.g. a Table of Contents) lost
# several top-level items entirely — the old _BlockExtractor had no stack,
# just flat _in_list/_list_items state, so starting a nested <ul>/<ol> mid
# <li> clobbered the outer list's already-collected items.


def test_html_to_blocks_nested_list_keeps_every_sibling_item():
    md = (
        "1. Introduction\n"
        "2. Database Objects\n"
        "    - 4.1 Datasources\n"
        "    - 4.2 Metadata Annotation\n"
        "3. Appendix\n"
    )
    blocks = html_to_blocks(md)
    assert len(blocks) == 1
    top_list = blocks[0]
    assert top_list["type"] == "list"
    assert top_list["ordered"] is True
    top_texts = [_run_texts(item["runs"]) for item in top_list["items"]]
    assert top_texts == [["Introduction"], ["Database Objects"], ["Appendix"]]

    objects_item = top_list["items"][1]
    assert objects_item["sublist"] is not None
    assert objects_item["sublist"]["ordered"] is False
    sub_texts = [_run_texts(item["runs"]) for item in objects_item["sublist"]["items"]]
    assert sub_texts == [["4.1 Datasources"], ["4.2 Metadata Annotation"]]

    # Siblings before/after the nested item carry no sublist of their own.
    assert top_list["items"][0]["sublist"] is None
    assert top_list["items"][2]["sublist"] is None


def test_html_to_blocks_loose_list_boundary_bug_is_worked_around():
    """The exact reported case: a blank line between a list item's text and
    its own indented sub-list used to make Python-Markdown lose track of
    the outer list's boundary entirely, silently swallowing every
    subsequent top-level item into the nested sub-list instead of keeping
    them as siblings — verified directly against Python-Markdown's raw HTML
    output, not guessed.
    """
    md = (
        "1. Introduction\n"
        "2. Database Objects\n"
        "\n"
        "    - 4.1 Datasources\n"
        "3. Raw Database DDL\n"
        "4. Appendix\n"
    )
    blocks = html_to_blocks(md)
    top_list = blocks[0]
    top_texts = [_run_texts(item["runs"]) for item in top_list["items"]]
    assert top_texts == [["Introduction"], ["Database Objects"], ["Raw Database DDL"], ["Appendix"]]
    assert top_list["items"][1]["sublist"]["items"][0]["runs"][0]["text"] == "4.1 Datasources"


# -- Literal &nbsp; artifacts ------------------------------------------
#
# Regression coverage for a real reported bug: a DDL code block pasted
# into Azure DevOps carried literal "&nbsp;" text (a copy/paste artifact
# from an HTML source) as indentation filler. Markdown's fenced_code
# extension HTML-escapes code content on the way in ("&" -> "&amp;"), and
# our parser correctly decodes that back on the way out — faithfully
# round-tripping whatever was actually in the source, including the
# literal "&nbsp;" text, which then showed up as visible garbage instead
# of the whitespace it was always meant to be.


def test_html_to_blocks_normalizes_literal_nbsp_in_fenced_code():
    md = "```sql\nCREATE TABLE t (\n    id&nbsp;&nbsp;&nbsp;&nbsp;UUID\n);\n```\n"
    blocks = html_to_blocks(md)
    code_block = next(b for b in blocks if b["type"] == "code")
    assert "&nbsp;" not in code_block["text"]
    assert "id    UUID" in code_block["text"]


def test_html_to_blocks_normalizes_literal_nbsp_in_prose_too():
    # Not just code — the same artifact can show up anywhere in a field.
    text = "# Notice\n\nPlease&nbsp;review this **before** the end of day."
    blocks = html_to_blocks(text)
    flat = blocks_to_plain_text(blocks)
    assert "&nbsp;" not in flat
    assert "Please review" in flat


def test_html_to_blocks_normalizes_numeric_and_decoded_nbsp_forms():
    assert "&#160;" not in blocks_to_plain_text(html_to_blocks("# H\n\nA&#160;B **bold**"))
    assert "\xa0" not in blocks_to_plain_text(html_to_blocks("# H\n\nA\xa0B **bold**"))


def test_html_to_blocks_ordered_list_alone_is_detected_as_markdown():
    """An ordered-list-only field (no headings/bold/table) previously fell
    through detection entirely — _MD_WEAK_SIGNALS only recognized
    unordered `-`/`*`/`+` markers, never `1.`/`2.` ones — combined with an
    unordered sub-list, two distinct weak signals now correctly trigger.
    """
    md = "1. Introduction\n2. Objects\n    - 2.1 Sub-item\n3. Appendix\n"
    blocks = html_to_blocks(md)
    assert blocks[0]["type"] == "list"
    assert blocks[0]["ordered"] is True
