"""3.2 Process Overview of the "Generate Formatted SRS" (v2) pipeline: each
Epic's Business Process Diagram followed by its own Features' Workflow
Diagrams, before the next Epic starts."""

import struct
import zlib
from io import BytesIO
from unittest.mock import MagicMock

from docx import Document

from src.tasks.srs_v2_builder import build_srs_document_v2

_HEADING_3_2 = "3.2 Process Overview"
_HEADING_3_3 = "3.3 Dependencies with Other Modules / Systems"


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + chunk(b"IEND", b"")
    )


def _minio() -> MagicMock:
    minio = MagicMock()
    minio.download_bytes.return_value = _png()
    return minio


def _text(text: str) -> dict:
    return {"type": "text", "runs": [{"text": text, "bold": False, "italic": False, "underline": False, "mono": False}]}


def _image(src: str) -> dict:
    return {"type": "image", "src": src}


def _node(work_item_type: str, azure_id: int, title: str, **overrides) -> dict:
    node = {
        "work_item_type": work_item_type,
        "azure_work_item_id": azure_id,
        "title": title,
        "state": "New",
        "description_blocks": [],
        "acceptance_criteria_blocks": [],
        "content_sections": [],
        "azure_url": f"https://dev.azure.com/org/proj/_workitems/edit/{azure_id}",
        "assets": [],
        "children": [],
    }
    node.update(overrides)
    return node


def _asset(src: str) -> dict:
    return {"bucket": "b", "object_key": f"key/{src}", "source_url": src}


def _epic(azure_id: int, title: str, diagram_src: str | None, features: list[dict]) -> dict:
    analysis_blocks = [_text("Business Process Diagram")]
    if diagram_src:
        analysis_blocks.append(_image(diagram_src))
    analysis_blocks += [_text("User Persona"), _text("Corporate banking user")]
    return _node(
        "Epic",
        azure_id,
        title,
        content_sections=[{"label": "Analysis", "blocks": analysis_blocks}],
        assets=[_asset(diagram_src)] if diagram_src else [],
        children=features,
    )


def _feature(azure_id: int, title: str, diagram_src: str | None) -> dict:
    blocks = [_text("Some intro prose that is not a diagram.")]
    if diagram_src:
        blocks += [_text("Workflow Diagram"), _image(diagram_src)]
    return _node(
        "Feature",
        azure_id,
        title,
        description_blocks=blocks,
        assets=[_asset(diagram_src)] if diagram_src else [],
    )


def _build(roots: list[dict]) -> Document:
    context = {
        "source_url": "https://dev.azure.com/org/proj",
        "generated_at": "2026-01-01T00:00:00Z",
        "snapshot_id": "snap-1",
        "total_count": len(roots),
        "ai_introduction": None,
        "roots": roots,
        "template_version": "v2",
    }
    return Document(BytesIO(build_srs_document_v2(context, _minio())))


def _section_3_2(document: Document) -> list[str]:
    """Bold labels and picture markers, in document order, between the 3.2
    and 3.3 headings."""
    items: list[str] = []
    collecting = False
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text == _HEADING_3_3:
            break
        if text == _HEADING_3_2:
            collecting = True
            continue
        if not collecting:
            continue
        if paragraph._p.xpath(".//w:drawing"):
            items.append("<image>")
        elif text:
            items.append(text)
    return items


def test_features_are_scoped_under_their_own_epic_in_order():
    roots = [
        _epic(
            1,
            "Epic A",
            "https://x/a.png",
            [_feature(11, "Feature a", "https://x/fa.png"), _feature(12, "Feature b", "https://x/fb.png")],
        ),
        _epic(2, "Epic B", "https://x/b.png", [_feature(21, "Feature c", "https://x/fc.png")]),
    ]

    assert _section_3_2(_build(roots)) == [
        "Epic - Epic A:",
        "<image>",
        "Feature - Feature a:",
        "<image>",
        "Feature - Feature b:",
        "<image>",
        "Epic - Epic B:",
        "<image>",
        "Feature - Feature c:",
        "<image>",
    ]


def test_only_the_diagram_is_pulled_not_other_subsections_or_prose():
    roots = [_epic(1, "Epic A", "https://x/a.png", [_feature(11, "Feature a", "https://x/fa.png")])]

    items = _section_3_2(_build(roots))

    assert "Corporate banking user" not in items
    assert "User Persona" not in items
    assert "Some intro prose that is not a diagram." not in items


def test_epic_without_diagram_keeps_heading_for_features_that_have_one():
    roots = [_epic(1, "Epic A", None, [_feature(11, "Feature a", "https://x/fa.png")])]

    assert _section_3_2(_build(roots)) == ["Epic - Epic A:", "Feature - Feature a:", "<image>"]


def test_feature_without_diagram_is_skipped_and_epic_without_any_is_omitted():
    roots = [
        _epic(1, "Epic A", "https://x/a.png", [_feature(11, "No diagram", None)]),
        _epic(2, "Epic B", None, [_feature(21, "Also none", None)]),
    ]

    assert _section_3_2(_build(roots)) == ["Epic - Epic A:", "<image>"]


def test_no_diagrams_anywhere_leaves_section_empty():
    assert _section_3_2(_build([_epic(1, "Epic A", None, [])])) == []


def test_missing_downloaded_asset_shows_visible_error_naming_the_source():
    epic = _epic(1, "Epic A", "https://x/a.png", [])
    epic["assets"] = []  # image referenced in the field, but its download never landed

    items = _section_3_2(_build([epic]))

    assert items[0] == "Epic - Epic A:"
    assert "Epic 1: Epic A" in items[1]



def test_real_org_shape_dedicated_fields_work_flow1_and_sequence_diagram():
    """Real data (Epic 118798 / Feature 118815): the Epic's diagram is the
    dedicated field Custom.WorkFlow1 and the Feature's is
    Custom.SequenceDiagram - not named subsections inside a bigger field."""
    epic_src, feature_src, other_src = "https://x/bpmn.png", "https://x/wf.png", "https://x/erd.png"
    feature = _node(
        "Feature",
        11,
        "CASA Account Information",
        content_sections=[{"label": "Sequence Diagram", "blocks": [_image(feature_src)]}],
        assets=[_asset(feature_src)],
    )
    epic = _node(
        "Epic",
        1,
        "Corporate Account & Portfolio Visibility",
        content_sections=[
            {"label": "ERD", "blocks": [_image(other_src)]},  # a different tab's diagram - must not be pulled
            {"label": "Work Flow1", "blocks": [_image(epic_src)]},
        ],
        assets=[_asset(epic_src), _asset(other_src)],
        children=[feature],
    )

    assert _section_3_2(_build([epic])) == [
        "Epic - Corporate Account & Portfolio Visibility:",
        "<image>",
        "Feature - CASA Account Information:",
        "<image>",
    ]


def test_other_diagram_fields_are_not_pulled_into_3_2():
    epic = _node(
        "Epic",
        1,
        "Epic A",
        content_sections=[
            {"label": "Context Diagram", "blocks": [_image("https://x/c.png")]},
            {"label": "Data Flow Diagram", "blocks": [_image("https://x/d.png")]},
        ],
        assets=[_asset("https://x/c.png"), _asset("https://x/d.png")],
    )

    assert _section_3_2(_build([epic])) == []
