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
    return {"text": text, "bold": False, "italic": False, "underline": False}


def _bold(text: str) -> dict:
    return {"text": text, "bold": True, "italic": False, "underline": False}


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
        {"type": "list", "items": [[_plain("Only admins may approve.")], [_plain("Every change is logged.")]]}
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
    item_runs = blocks[0]["items"][0]
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
        {"type": "list", "items": [[_plain("one")], [_plain("two")]]},
        {"type": "table", "rows": [[[_plain("a")], [_plain("b")]], [[_plain("c")], [_plain("d")]]]},
    ]
    flat = blocks_to_plain_text(blocks)
    assert flat == "Intro.\none\ntwo\na | b\nc | d"


def test_blocks_to_plain_text_empty_list_returns_empty_string():
    assert blocks_to_plain_text([]) == ""
