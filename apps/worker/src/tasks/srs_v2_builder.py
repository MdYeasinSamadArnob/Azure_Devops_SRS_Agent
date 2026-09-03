"""Builds the SRS document from the NEW ERA_SRS_Template_V2.1 template —
the "Generate Formatted SRS" path, alongside (not replacing) the existing
`docx_builder.py` / "Generate Document" path.

This is a direct port of the verified logic from
`tools/template_playground/render_template.py` (see backlog tasks 1, 3, 4,
5, 7, 8, 9, 10, 13, 30 — all confirmed structurally correct through several
rounds of hands-on review) into the real pipeline, per backlog task-15.

Deliberately narrow scope, matching exactly what was actually verified:
cover page, header, real TOC field, and the Document Control section
(1.1 filled from config, 1.2/1.3/1.4/RTM shape-preserved-but-emptied).
Sections 2-10 are left exactly as the template's own guidance/placeholder
text — the dynamic Azure-pull / LLM-synthesis / regex-ID-extraction rules
for those (docs/srs-content-mapping-spec.md, backlog tasks 16-29) are
separate, not-yet-implemented work. This is why the template is loaded
WITHOUT stripping its body content (unlike `docx_builder.py`'s
`_load_base_document()`) — the template already has the right guidance
text for everything this module doesn't touch.
"""

from __future__ import annotations

import copy
import logging
import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, RGBColor
from docx.text.paragraph import Paragraph
from srs_core.rendering.html_text import blocks_to_plain_text

from src.tasks.docx_builder import resolve_document_title

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "templates"
TEMPLATE_PATH = _TEMPLATE_DIR / "ERA_SRS_Template_V2.1.docx"

DEFAULT_ADDRESS_BLOCK = (
    "Fareast Tower, 35 Topkhana Road, (Level-3), Dhaka-1000\n"
    "Phone: +88 019 7833 3448\nEmail: info@erainfotechbd.com"
)
CONTACT_EMAIL = "info@erainfotechbd.com"

HYPERLINK_BLUE = RGBColor(0x05, 0x63, 0xC1)  # Word's own default hyperlink blue
# Same navy used by every other data table's header row in this template
# (pixel-sampled from the source PDF during the original reconstruction -
# see build_v21_template.py) - matched here for visual consistency, since
# backlog task-25/26's per-story tables are newly built, not edited from
# an existing template table like everything else in this document.
NAVY_FILL = "1F3863"
ZEBRA_FILL = "E7E6E6"  # label-column shading on label/value tables, e.g. 1.1 and the User Story info table
# Matches the reviewed margins (0.75in sides) and default cell margins
# (build_v21_template.py's own MARGIN_LEFT_IN/RIGHT_IN and
# CELL_MARGIN_*_DXA) - every table in this document, including the new
# ones task-25/26 build from scratch, needs to agree on these or they'll
# visibly stick out from the rest of the page.
USABLE_WIDTH_IN = 8.5 - 0.75 - 0.75
CELL_MARGIN_TOP_DXA = 72  # 0.05in
CELL_MARGIN_BOTTOM_DXA = 72
CELL_MARGIN_LEFT_DXA = 115  # 0.08in
CELL_MARGIN_RIGHT_DXA = 115

_TBLPR_CHILD_ORDER = [
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
    "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
]


def _set_cell_shading(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _apply_dynamic_table_formatting(table, col_widths_in: list[float]) -> None:
    """Fixed layout + explicit column widths + the reviewed default cell
    margins - the same treatment every table already ported from the base
    template carries (see build_v21_template.py's _apply_table_formatting,
    which this mirrors), but these two tables never went through that
    reconstruction pass - they're newly built here by task-25/26, so
    without this they'd be the only tables in the document still on
    Word's "autofit to contents" default, visibly inconsistent with
    everything else on the page.
    """
    table.autofit = False  # -> <w:tblLayout w:type="fixed"/>
    for col, width_in in zip(table.columns, col_widths_in):
        col.width = Inches(width_in)
    for row in table.rows:
        for cell, width_in in zip(row.cells, col_widths_in):
            cell.width = Inches(width_in)

    tblPr = table._tbl.tblPr
    cell_mar = OxmlElement("w:tblCellMar")
    for tag, value in (
        ("w:top", CELL_MARGIN_TOP_DXA),
        ("w:left", CELL_MARGIN_LEFT_DXA),
        ("w:bottom", CELL_MARGIN_BOTTOM_DXA),
        ("w:right", CELL_MARGIN_RIGHT_DXA),
    ):
        el = OxmlElement(tag)
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        cell_mar.append(el)
    # tblCellMar must come after tblLayout and before tblLook in CT_TblPr's
    # schema order - a blind append() would put it last (after tblLook,
    # which table.style/.autofit already added), which Word silently drops
    # on save/reopen. Insert in schema order instead of trusting
    # append-goes-last (same class of bug as the header tab-stop issue
    # found in build_v21_template.py - see that module's own notes).
    new_idx = _TBLPR_CHILD_ORDER.index("tblCellMar")
    for child in tblPr:
        local = child.tag.split("}")[-1]
        try:
            child_idx = _TBLPR_CHILD_ORDER.index(local)
        except ValueError:
            continue
        if child_idx > new_idx:
            child.addprevious(cell_mar)
            break
    else:
        tblPr.append(cell_mar)


# ---------------------------------------------------------------------------
# Field mapping: context["document_metadata"] (backlog task-6's 12-field
# set — the 11 Document Information fields plus "client", which the cover
# page needs but the 1.1 table doesn't) -> the cover_page / document_info
# dicts render_template.py's fill functions expect.
# ---------------------------------------------------------------------------


def _format_date_display(iso_date: str | None) -> str | None:
    """The frontend's date inputs send "YYYY-MM-DD"; the template shows
    "DD Month YYYY". Falls back to the raw value unchanged if it's not
    that exact shape, rather than dropping a value someone typed by hand
    directly into a future non-browser caller of this same endpoint.
    """
    if not iso_date:
        return None
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d %B %Y")
    except ValueError:
        return iso_date


def _cover_page_from_metadata(document_metadata: dict, context: dict) -> dict:
    document_title = resolve_document_title(context)
    date_created = _format_date_display(document_metadata.get("date_created")) or date.today().strftime("%d %B %Y")
    return {
        "module_name": document_title,
        "module_code": document_metadata.get("module_code") or "",
        "document_id": document_metadata.get("document_id") or "",
        "prepared_by": document_metadata.get("document_owner") or "ERA Info Tech Ltd.",
        "client": document_metadata.get("client") or "",
        "date": date_created,
        "classification": document_metadata.get("classification") or "CONFIDENTIAL",
        "status": document_metadata.get("document_status") or "Draft",
        # Always the template's own real contact info, exactly like the
        # verified isolated script - this was never meant to be
        # per-generation configurable, only the "not required, has a real
        # default" behavior needed proving.
        "address_block": "",
    }


def _document_info_from_metadata(document_metadata: dict, cover_page: dict) -> dict:
    date_submitted = _format_date_display(document_metadata.get("date_submitted")) or cover_page["date"]
    return {
        "Document ID": cover_page["document_id"],
        "Module Code": cover_page["module_code"],
        "Document Title": cover_page["module_name"],
        "Document Owner": document_metadata.get("document_owner") or "",
        "Related BRD": document_metadata.get("related_brd") or "",
        "Date Created": cover_page["date"],
        "Date Submitted": date_submitted,
        "Document Status": cover_page["status"],
        "Document Version": document_metadata.get("document_version") or "0.1",
        "Classification": cover_page["classification"],
        "Review Cycle": document_metadata.get("review_cycle") or "Per change or on stakeholder request",
    }


def _header_top_right_from(document_title: str) -> str:
    return f"SRS - {document_title}" if document_title else "SRS Template"


# ---------------------------------------------------------------------------
# Cover page - in-place text edits (ported verbatim from render_template.py)
#
# Deliberately NOT the "strip body, rebuild from scratch" technique
# docx_builder.py uses for the OLD org template - this template has a
# genuine section break between the cover page (no header/footer) and
# everything after the TOC (header/footer applies). Stripping every body
# child except the trailing sectPr would also delete the cover page's OWN
# section-break paragraph and collapse the document to one section, putting
# the header/footer on the cover page too. So the cover page's existing
# paragraphs get edited in place instead.
# ---------------------------------------------------------------------------


def _run_is_bold(run_element) -> bool:
    rpr = run_element.find(qn("w:rPr"))
    return rpr is not None and rpr.find(qn("w:b")) is not None


def _replace_value_runs(paragraph_element, new_value: str) -> None:
    """Cover-page label/value lines are `<bold label run(s)><plain value
    run(s)>`. Keeps the label run(s) untouched, collapses the plain value
    run(s) into one new run carrying the same formatting as the last
    existing value run (so e.g. Classification's red stays red).
    """
    runs = paragraph_element.findall(qn("w:r"))
    value_runs = [r for r in runs if not _run_is_bold(r)]
    if not value_runs:
        return
    keep, drop = value_runs[0], value_runs[1:]
    for r in drop:
        r.getparent().remove(r)
    t = keep.find(qn("w:t"))
    if t is None:
        t = OxmlElement("w:t")
        keep.append(t)
    t.text = new_value
    t.set(qn("xml:space"), "preserve")


def _replace_whole_paragraph_text(paragraph_element, new_value: str) -> None:
    """For cover-page lines that are just one plain value with no label
    prefix (module name, module code) - collapse to a single run.
    """
    runs = paragraph_element.findall(qn("w:r"))
    if not runs:
        return
    keep, drop = runs[0], runs[1:]
    for r in drop:
        r.getparent().remove(r)
    t = keep.find(qn("w:t"))
    if t is None:
        t = OxmlElement("w:t")
        keep.append(t)
    t.text = new_value
    t.set(qn("xml:space"), "preserve")


def _add_hyperlink(paragraph: Paragraph, url: str, display_text: str) -> None:
    """python-docx has no high-level hyperlink API - a real hyperlink is a
    relationship (added to the paragraph's part) plus a
    <w:hyperlink r:id="..."> element wrapping its own run, not something
    add_run() can produce. Styled blue + underlined to match how a real
    hyperlink actually looks (and how the source template renders its own
    email link), not left at plain body-text styling.
    """
    part = paragraph.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), str(HYPERLINK_BLUE))
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    run.append(rPr)

    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = display_text
    run.append(t)

    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_paragraph_lines_with_email_link(paragraph: Paragraph, lines: list[str], *, email_display: str, email_url: str) -> None:
    """Real line breaks (w:br via add_break) between `lines` - a literal
    "\\n" left inside a run's own text is NOT a line break in OOXML, it's
    whitespace that collapses away on save/reload. Wherever a line contains
    `email_display` verbatim, that substring becomes a real mailto:
    hyperlink (display text unchanged).
    """
    for i, line in enumerate(lines):
        if i > 0:
            br_run = paragraph.add_run()
            br_run.add_break()
        idx = line.find(email_display)
        if idx == -1:
            paragraph.add_run(line)
            continue
        before, after = line[:idx], line[idx + len(email_display):]
        if before:
            paragraph.add_run(before)
        _add_hyperlink(paragraph, email_url, email_display)
        if after:
            paragraph.add_run(after)


def update_cover_page(document: Document, fields: dict) -> None:
    children = list(document.element.body.iterchildren())
    # Confirmed against the real template (see backlog task-3/task-30):
    # paragraphs 0-15 are the cover page, 16 carries the section break, 17
    # is the "Table of Contents" heading. Indices below match that layout.
    _replace_whole_paragraph_text(children[1], f"[{fields['module_name']}]")
    _replace_whole_paragraph_text(children[2], f"[{fields['module_code']}]")
    _replace_value_runs(children[3], fields["document_id"])
    _replace_value_runs(children[4], fields["prepared_by"])
    _replace_value_runs(children[5], fields["client"])
    _replace_value_runs(children[6], fields["date"])
    _replace_value_runs(children[7], fields["classification"])
    _replace_value_runs(children[8], fields["status"])

    # Address block (paragraph 14) - this is where "not required, falls
    # back to the org's real default contact info" actually happens.
    address_paragraph = Paragraph(children[14], document)
    address_paragraph.clear()
    address_text = fields["address_block"].strip() or DEFAULT_ADDRESS_BLOCK
    _add_paragraph_lines_with_email_link(
        address_paragraph, address_text.split("\n"),
        email_display=CONTACT_EMAIL, email_url=f"mailto:{CONTACT_EMAIL}",
    )


def update_header(document: Document, top_right_text: str) -> None:
    # Header layout is one paragraph, one run per side: "ERA InfoTech
    # Limited" run, then a SECOND run holding both the w:tab character AND
    # the top-right text's w:t as siblings (`<w:r><w:tab/><w:t>...</w:t></w:r>`)
    # - not two separate runs. The tab-carrying run's own text is what changes.
    header_part = document.sections[-1].header.part.element
    for paragraph_element in header_part.iter(qn("w:p")):
        for run_element in paragraph_element.findall(qn("w:r")):
            if run_element.find(qn("w:tab")) is None:
                continue
            t = run_element.find(qn("w:t"))
            if t is None:
                t = OxmlElement("w:t")
                run_element.append(t)
            t.text = top_right_text
            t.set(qn("xml:space"), "preserve")


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def fill_document_information_table(table, fields: dict) -> None:
    """1.1 - an 11-row label/value table, row order matches document_info's
    key order exactly (verified against the real template).
    """
    for row, (_label, value) in zip(table.rows, fields.items()):
        value_cell = row.cells[1]
        value_cell.text = value


def blank_table_data_rows(table, *, header_rows: int = 1) -> None:
    """1.2/1.3/1.4 and 9's RTM table all keep their real row/column shape
    but every non-header cell goes blank - manually filled in by hand after
    generation (backlog task-7: the app never auto-populates these, so
    there's no stale-vs-manual-edit conflict risk on a later regenerate).
    """
    for row in table.rows[header_rows:]:
        for cell in row.cells:
            cell.text = ""


def _populate_table_rows(table, rows: list[list[str]]) -> None:
    """Resizes `table` (below its header row) to hold exactly `rows` -
    reuses existing sample rows first, adds more via table.add_row() if
    there are more entries than the template shipped with, removes any
    leftover unused rows if fewer. Shared by every dynamically-sized
    Azure/LLM-sourced table in this module (2.3 Definitions, 4.1 Epic
    Summary, 4.2 Feature List, ...) - a template shipping N sample rows
    doesn't mean a real selection has exactly N of anything.

    Falls back to the same blank-shape treatment as every other manual
    table (backlog task-7's precedent) if `rows` is empty - "no source
    content" must never mean the template's own canned sample rows get
    silently passed off as real, generated content.
    """
    if not rows:
        blank_table_data_rows(table)
        return

    data_rows = table.rows[1:]
    for i, values in enumerate(rows):
        row = data_rows[i] if i < len(data_rows) else table.add_row()
        for col, value in enumerate(values):
            row.cells[col].text = value

    for row in data_rows[len(rows):]:
        row._tr.getparent().remove(row._tr)


def _populate_definitions_table(table, definitions: list[dict[str, str]] | None) -> None:
    """2.3 - backlog task-18: the LLM decides the WHOLE term list, not just
    one templated row - see _populate_table_rows for the resize/fallback
    behavior this relies on.
    """
    _populate_table_rows(table, [[e["term"], e["definition"]] for e in definitions or []])


# ---------------------------------------------------------------------------
# Section 2/3 narrative placeholders
#
# The template's own body text for these paragraphs is bracketed AUTHORING
# GUIDANCE ("[State the purpose of this SRS...]") meant for a human editing
# the blank template by hand - it must never appear verbatim in an actually
# GENERATED document, so every one of these paragraphs gets overwritten
# here, either with real LLM content (2.2/3.1) or left genuinely empty
# (2.1, 3.2 - backlog tasks 16, 21). Indices confirmed directly against
# ERA_SRS_Template_V2.1.docx (build_v21_template.py's build_section_2/3
# produce this exact paragraph layout) - re-confirm these if that builder
# script changes section 2/3's structure.
# ---------------------------------------------------------------------------

PARA_2_1_PURPOSE = 37
PARA_2_2_SCOPE = 40
# 2.4's 4 sample bullet paragraphs (backlog task-19) - REMOVING 3 of them
# shifts every later paragraph index down by 3, so anything below index 49
# (namely 3.1 at 60, 3.2 at 63, 3.3 at 67-69, 3.5 at 75-76) MUST be
# read/written before this range is touched.
PARA_2_4_REFERENCES_FIRST = 46
PARA_2_4_REFERENCES_COUNT = 4
PARA_3_1_SOLUTION_OVERVIEW = 60
PARA_3_2_PROCESS_OVERVIEW = 63
PARA_3_3_DEPENDENCIES_FIRST = 67
PARA_3_3_DEPENDENCIES_COUNT = 3
PARA_3_5_ASSUMPTIONS_FIRST = 75
PARA_3_5_ASSUMPTIONS_COUNT = 2
# 3.4/3.6 are TABLES (indices 5/6 in document.tables), not paragraphs -
# unaffected by 2.4's paragraph-removal, handled alongside the other tables
# in build_srs_document_v2 instead of here.


def _set_placeholder_paragraph_text(document: Document, index: int, text: str | None) -> None:
    """Collapses paragraph `index` to a single run carrying `text` (or no
    run at all if `text` is falsy) - same "collapse to one run, don't leave
    stray old-formatting runs behind" technique as the cover page's
    _replace_whole_paragraph_text, just via the higher-level python-docx
    Paragraph/Run API since these are plain body paragraphs, not the cover
    page's label/value lines.
    """
    paragraph = document.paragraphs[index]
    runs = paragraph.runs
    if not runs:
        if text:
            paragraph.add_run(text)
        return
    keep, drop = runs[0], runs[1:]
    for r in drop:
        r._element.getparent().remove(r._element)
    keep.text = text or ""


def _clear_bullet_list_to_one_empty_item(document: Document, first_index: int, count: int) -> None:
    """Manual, empty placeholder for a bullet-styled section (2.4 -
    backlog task-19) - the list-shaped equivalent of task-16's single-
    empty-paragraph pattern for a plain paragraph: collapses `count` sample
    bullet paragraphs starting at `first_index` down to ONE empty
    bullet-styled paragraph, ready to type into, rather than leaving the
    template's bracketed sample references in a delivered document.
    """
    paragraphs = [document.paragraphs[first_index + i] for i in range(count)]
    _set_placeholder_paragraph_text(document, first_index, None)
    for p in paragraphs[1:]:
        p._element.getparent().remove(p._element)


# ---------------------------------------------------------------------------
# Section 3.3-3.6 - Epic-level Azure pull (backlog task-22)
#
# The exact Azure custom-field name for "Dependencies"/"User Roles"/
# "Assumptions and Constraints"/"Out of Scope" is explicitly unconfirmed
# (docs/srs-content-mapping-spec.md) - every org customizes its process
# template differently. Discovered by LABEL instead, via the same generic
# custom-field mechanism already used everywhere else in this pipeline
# (srs_core.parsing.custom_fields.extract_content_fields, already run for
# every work item in normalize_content's _build_hierarchy_tree and exposed
# as each node's "content_sections") - not hardcoded to one org's field
# reference name. Re-tune these patterns once a real org's exact labels are
# confirmed.
# ---------------------------------------------------------------------------

_DEPENDENCIES_LABEL_RE = re.compile(r"depend", re.IGNORECASE)
_ROLES_LABEL_RE = re.compile(r"role|persona", re.IGNORECASE)
_ASSUMPTIONS_LABEL_RE = re.compile(r"assumption|constraint", re.IGNORECASE)
# "Out of Scope" has 4 characters (" of ") between "out" and "scope" - a
# {0,3} bound here was a real bug caught in testing: it silently matched
# nothing against the template's own field label. {0,8} covers that plus
# reasonable variants ("Out-of-Scope", "Out Of  Scope").
_OUT_OF_SCOPE_LABEL_RE = re.compile(r"out.{0,8}scope", re.IGNORECASE)


def _collect_epic_content_lines(context: dict, label_pattern: re.Pattern[str]) -> list[str]:
    """One line per bullet/list-item/paragraph found in every Epic's
    content_sections whose label matches `label_pattern` - reuses
    blocks_to_plain_text's existing one-item-per-line behavior (list items,
    table rows, and paragraphs each already land on their own line) rather
    than re-walking the block structure.
    """
    roots = context.get("roots") or []
    epics = [r for r in roots if r.get("work_item_type") == "Epic"]
    lines: list[str] = []
    for epic in epics:
        for section in epic.get("content_sections") or []:
            if label_pattern.search(section.get("label") or ""):
                text = blocks_to_plain_text(section.get("blocks") or [])
                lines.extend(line.strip() for line in text.split("\n") if line.strip())
    return lines


def _render_bullets_at(document: Document, first_index: int, sample_count: int, lines: list[str]) -> None:
    """3.3/3.5 - backlog task-22: replaces the template's `sample_count`
    bracketed sample bullets starting at `first_index` with real content
    (one bullet per line), growing or shrinking the list to fit - a
    template shipping 3 sample bullets doesn't mean every real Epic has
    exactly 3 dependencies. Falls back to the same single-empty-bullet
    "manual placeholder" treatment as task-19 if no matching Azure content
    was found for any Epic in the selection.
    """
    if not lines:
        _clear_bullet_list_to_one_empty_item(document, first_index, sample_count)
        return

    anchor = document.paragraphs[first_index]
    sample_paragraphs = [document.paragraphs[first_index + i] for i in range(sample_count)]
    _set_placeholder_paragraph_text(document, first_index, lines[0])

    insert_after = anchor._p
    for line in lines[1:]:
        new_p = copy.deepcopy(anchor._p)
        for run_element in new_p.findall(qn("w:r")):
            new_p.remove(run_element)
        Paragraph(new_p, document).add_run(line)
        insert_after.addnext(new_p)
        insert_after = new_p

    # Leftover original sample bullets beyond the first are no longer
    # needed - remove by their own element reference (captured before any
    # insertion above), safe regardless of how many clones were inserted.
    for p in sample_paragraphs[1:]:
        p._element.getparent().remove(p._element)


def _populate_azure_sourced_table(table, lines: list[str], *, content_col: int = 0) -> None:
    """3.4/3.6 - backlog task-22: puts each Azure-sourced line into the
    table's primary content column (SL, if the table has one at column 0,
    auto-increments; every other column - e.g. 3.4's "Decision Authority",
    3.6's "Description" - is left blank for manual completion, since
    reliably splitting free-text Azure content into those judgment-call
    columns isn't something a fixed heuristic can do, and the exact source
    field shape is still unconfirmed). Resizes the table to fit, same
    reuse-then-add-then-trim pattern as _populate_definitions_table
    (backlog task-18). Falls back to the template's own blank-shape
    treatment (backlog task-7's precedent) if no matching content was found.
    """
    if not lines:
        blank_table_data_rows(table)
        return

    data_rows = table.rows[1:]
    has_sl_column = content_col == 1
    for i, line in enumerate(lines):
        row = data_rows[i] if i < len(data_rows) else table.add_row()
        if has_sl_column:
            row.cells[0].text = str(i + 1)
        row.cells[content_col].text = line
        for extra_col in range(content_col + 1, len(row.cells)):
            row.cells[extra_col].text = ""

    for row in data_rows[len(lines):]:
        row._tr.getparent().remove(row._tr)


# ---------------------------------------------------------------------------
# Section 4 - Feature Catalogue (backlog tasks 23, 24)
# ---------------------------------------------------------------------------

# Neither the spec nor the template defines how Epic/Feature IDs are meant
# to be derived (unlike Business Rules/NFRs/Integration/Reporting, which
# all have explicit ID-generation rules) - the real, stable, already-unique
# identifier every work item genuinely has is its own Azure ID, so that's
# what these are built from. Revisit if a real naming convention surfaces.
_EPIC_ID_PREFIX = "EPIC"
_FEATURE_ID_PREFIX = "FEAT"

_REQUIREMENT_DESCRIPTION_LABEL_RE = re.compile(r"requirement.{0,5}desc", re.IGNORECASE)
_ENTRY_CRITERIA_LABEL_RE = re.compile(r"entry.{0,5}criteria", re.IGNORECASE)
_EXIT_CRITERIA_LABEL_RE = re.compile(r"exit.{0,5}criteria", re.IGNORECASE)
# The User Story's "Requirement" tab (backlog task-26) - deliberately
# broader than the other _LABEL_RE patterns (just "requirement", no
# qualifier) since this is a Story-level field, not competing with the
# Epic-level "Requirement Description" field _REQUIREMENT_DESCRIPTION_LABEL_RE
# matches (different node entirely - each is only ever searched against its
# own work item's content_sections). Also matches "Business Rule(s)" as an
# alternate label - real-world Azure orgs were observed (2026-09-03, first
# real-data test) naming this field "Business Rules" outright rather than
# "Requirement", so the original requirement-only pattern silently found
# nothing and the whole Business Rules subsection was omitted.
_REQUIREMENT_TAB_LABEL_RE = re.compile(r"requirement|business.{0,5}rule", re.IGNORECASE)
# The Epic's "Analysis" tab (backlog task-27) - source for section 6's
# Non-Functional Requirements, per docs/srs-content-mapping-spec.md (exact
# Azure field name unconfirmed there too, same caveat as every other
# label-matched field in this module). Also matches "Non Functional
# Requirements" as an alternate label - the first real org tested
# (2026-09-03 follow-up) names this field "Custom.NonFunctionalRequirements"
# outright, not "Analysis" at all - same class of gap as
# _REQUIREMENT_TAB_LABEL_RE's earlier "Business Rules" follow-up.
_ANALYSIS_TAB_LABEL_RE = re.compile(r"analysis|non.{0,3}functional", re.IGNORECASE)
# An explicit item ID (Business Rule - task-26, or NFR - task-27) needs at
# least one letter AND one digit (e.g. "BR-001", "BRL01", "NFR-01") followed
# by a separator - a bare numbered-list marker ("1. text") has no letters
# and must NOT count as an "explicit ID" here, or every ordinary numbered
# list would look labeled. Shared by both since it's the same either/or
# rule in both places: explicit IDs in the source get extracted as-is,
# otherwise every line gets a generated id instead.
# re.DOTALL so "(.+)$" can still span an item whose own nested sub-bullets
# were folded into this same line as embedded "\n"s (see
# _list_items_merged_with_sublists) - without it, "." stops at the first
# embedded newline and an item with sub-bullets would never match even when
# every sibling item in the same list has an explicit ID, wrongly tipping
# the whole list into the "no IDs given" generated-id branch.
_EXPLICIT_ITEM_ID_RE = re.compile(r"^\s*([A-Za-z]{1,10}[-_ ]?\d{1,4})\s*[:.\-–]\s*(.+)$", re.DOTALL)


def _matching_content_section_blocks(node: dict, label_pattern: re.Pattern[str]) -> list[dict]:
    """First content_section on `node` whose label matches `label_pattern`
    and has actual content, as RAW blocks (not flattened to text) - lets a
    caller that cares about list/sublist structure (see
    _list_derived_lines) inspect it directly instead of losing it
    to blocks_to_plain_text's flat one-line-per-item join. Same
    label-matching/first-non-empty-match rule as _matching_content_section_text,
    which is now just this plus a flatten step.
    """
    for section in node.get("content_sections") or []:
        if label_pattern.search(section.get("label") or ""):
            blocks = section.get("blocks") or []
            if blocks_to_plain_text(blocks):
                return blocks
    return []


def _matching_content_section_text(node: dict, label_pattern: re.Pattern[str]) -> str:
    """First content_section on `node` whose label matches `label_pattern`,
    flattened to plain text, or "" if none matches - the shared
    label-matching lookup for any single custom field (Epic's Requirement
    Description, a User Story's Entry/Exit Criteria, ...) where the exact
    Azure field name is unconfirmed (see docs/srs-content-mapping-spec.md)
    but its label is expected to roughly match.
    """
    return blocks_to_plain_text(_matching_content_section_blocks(node, label_pattern))


def _flatten_by_type(roots: list[dict], work_item_type: str) -> list[dict]:
    """Every node of `work_item_type` anywhere in the tree, not just at the
    top level - a Feature is normally nested under its Epic, but a
    partial-selection edge case can also put one at the top (see
    _build_hierarchy_tree's own docstring), so this walks the whole tree
    rather than assuming a fixed depth.
    """
    found: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            if node.get("work_item_type") == work_item_type:
                found.append(node)
            walk(node.get("children") or [])

    walk(roots)
    return found


def _epic_requirement_description(epic: dict) -> str:
    """4.1's Description column - backlog task-23: sourced from the Epic's
    "Requirement Description" field per docs/srs-content-mapping-spec.md
    (exact Azure field name unconfirmed there too - matched by label, same
    approach as task-22's 3.3-3.6). Falls back to the Epic's own standard
    Description field if no custom field with a matching label exists,
    rather than leaving the row's description blank when there's
    perfectly good content sitting in the standard field.
    """
    return _matching_content_section_text(epic, _REQUIREMENT_DESCRIPTION_LABEL_RE) or blocks_to_plain_text(
        epic.get("description_blocks") or []
    )


def _populate_epic_summary_table(table, epics: list[dict]) -> None:
    """4.1 Epic / Functional Area Summary - backlog task-23: one row per
    Epic in the sealed selection, every Epic listed (not sampled/truncated
    - unlike the LLM grounding elsewhere in this module, this is a direct
    SOURCE_EXTRACTED listing, not a synthesis, so nothing should be left
    out).
    """
    rows = [
        [f"{_EPIC_ID_PREFIX}-{epic['azure_work_item_id']}", epic.get("title") or "", _epic_requirement_description(epic)]
        for epic in epics
    ]
    _populate_table_rows(table, rows)


def _feature_priority_label(feature: dict) -> str:
    """Azure Priority 1-2 -> "Must Have", 3-4 -> "Should Have" (backlog
    task-24). Priority is stored as a string (not guaranteed numeric - see
    generate_pipeline.py's own note on the field) and whether it ever falls
    outside 1-4 is an explicitly open question in
    docs/srs-content-mapping-spec.md - left blank rather than guessed for
    anything that doesn't parse as 1-4, so an unexpected value is visibly
    incomplete rather than silently mislabeled.
    """
    try:
        priority = int(str(feature.get("priority") or "").strip())
    except ValueError:
        return ""
    if priority in (1, 2):
        return "Must Have"
    if priority in (3, 4):
        return "Should Have"
    return ""


def _populate_feature_list_table(table, features: list[dict]) -> None:
    """4.2 Feature List - backlog task-24: one row per Feature, every
    Feature listed. Source BR ID is always the literal "TBD" per the spec
    (Business Rules aren't linked back to a specific Feature anywhere in
    this org's process).
    """
    rows = [
        [
            f"{_FEATURE_ID_PREFIX}-{feature['azure_work_item_id']}",
            feature.get("title") or "",
            blocks_to_plain_text(feature.get("description_blocks") or []),
            _feature_priority_label(feature),
            "TBD",
        ]
        for feature in features
    ]
    _populate_table_rows(table, rows)


def _apply_section_2_3_placeholders(document: Document, context: dict) -> None:
    """All paragraph-index-based edits for sections 2-3, applied in STRICT
    DESCENDING original-index order (bottom of the document first).

    Every PARA_* constant above was measured once, against the untouched
    template. Any edit that inserts or removes paragraphs (2.4's trim,
    3.3/3.5's Azure-content rendering - the latter can insert MORE
    paragraphs than the template shipped, not just remove) shifts every
    later paragraph's real position. Processing bottom-to-top means that by
    the time any given index is used, everything AFTER it in the document
    has already been finalized (so a later shift can't matter - that
    section is done), and nothing BEFORE it has been touched yet (so ITS
    index is still the original, correct one). Processing in document
    order, as earlier revisions of this function did, is what let a
    similar bug slip through once already (see backlog task-19's notes) -
    keep this order if more sections are added here.
    """
    # 3.5 Assumptions and Constraints - Epic-level Azure pull, read-only
    # (backlog task-22). Falls back to one empty bullet if no Epic has
    # matching content.
    _render_bullets_at(
        document, PARA_3_5_ASSUMPTIONS_FIRST, PARA_3_5_ASSUMPTIONS_COUNT,
        _collect_epic_content_lines(context, _ASSUMPTIONS_LABEL_RE),
    )

    # 3.3 Dependencies with Other Modules / Systems - same pattern.
    _render_bullets_at(
        document, PARA_3_3_DEPENDENCIES_FIRST, PARA_3_3_DEPENDENCIES_COUNT,
        _collect_epic_content_lines(context, _DEPENDENCIES_LABEL_RE),
    )

    # 3.2 Process Overview - manual, always genuinely empty (backlog task-21).
    _set_placeholder_paragraph_text(document, PARA_3_2_PROCESS_OVERVIEW, None)

    # 3.1 Solution Overview - brief LLM synthesis (backlog task-17), computed
    # in run_llm_rules. Falls back to empty if the LLM was unavailable.
    _set_placeholder_paragraph_text(document, PARA_3_1_SOLUTION_OVERVIEW, context.get("v2_solution_overview"))

    # 2.4 References - manual, empty placeholder (backlog task-19).
    _clear_bullet_list_to_one_empty_item(document, PARA_2_4_REFERENCES_FIRST, PARA_2_4_REFERENCES_COUNT)

    # 2.2 Scope - same LLM pattern as 3.1 (backlog task-17).
    _set_placeholder_paragraph_text(document, PARA_2_2_SCOPE, context.get("v2_scope"))

    # 2.1 Purpose - manual, always genuinely empty (backlog task-16).
    _set_placeholder_paragraph_text(document, PARA_2_1_PURPOSE, None)


# ---------------------------------------------------------------------------
# Section 5 - Functional Requirements: Feature-under-Epic grouping and
# document-wide User Story numbering (backlog task-25)
#
# Unlike every section before it, this one can't be edited by overwriting
# text in fixed-shape paragraphs/tables - the template ships exactly ONE
# worked Epic/Feature/User-Story example, but a real selection has however
# many Epics/Features/Stories it has. The old example content is removed
# entirely and replaced with freshly BUILT content, sized to fit.
#
# Locate the section by its own heading TEXT, not a hardcoded paragraph
# index - by this point in the document, task-19/22's dynamic-length
# bullet rendering earlier in sections 2-3 has already made "the original
# index" meaningless this far into the body. This is the more robust
# technique and should be preferred over hardcoded indices generally.
# ---------------------------------------------------------------------------

_STORY_NUMBER_WIDTH = 3


def _find_paragraph(document: Document, text: str) -> Paragraph:
    for p in document.paragraphs:
        if p.text.strip() == text:
            return p
    raise RuntimeError(f"expected paragraph {text!r} not found in the V2 template - did its structure change?")


def _find_table_by_first_header_cell(document: Document, text: str) -> object:
    for table in document.tables:
        if table.rows and table.rows[0].cells and table.rows[0].cells[0].text.strip() == text:
            return table
    raise RuntimeError(f"expected a table with header {text!r} not found in the V2 template - did its structure change?")


def _runs_to_text(runs: list[dict]) -> str:
    return "".join(r.get("text") or "" for r in runs)


def _list_items_merged_with_sublists(items: list[dict], indent: int = 0) -> list[str]:
    """Like srs_core's own _list_items_to_lines, but a nested sublist is NOT
    split out into its own separate top-level lines - each of its items is
    folded into its PARENT item's own line instead (joined by "\\n",
    indented and dash-prefixed one level deeper per nesting level).

    This matters because a Business Rule's nested sub-bullets are an
    elaboration of that one rule (e.g. "...download the statement in
    either of the following formats:" / "- PDF" / "- Excel" all describe
    ONE rule), not separate rules of their own. Flattening them to
    one-line-per-item (blocks_to_plain_text's behavior, meant for LLM
    grounding where line-per-item is exactly what's wanted) would either
    turn "PDF"/"Excel" into their own meaningless generated rules, or -
    depending on the exact source HTML - drop them altogether; this keeps
    them attached to the rule they actually belong to (backlog task-26's
    2026-09-03 follow-up, reported against real Azure data).

    Only top-level items produce entries in the returned list; every
    deeper level is merged text within its ancestor's own entry.
    """
    lines: list[str] = []
    for item in items:
        prefix = "  " * (indent - 1) + "- " if indent else ""
        text = prefix + _runs_to_text(item.get("runs") or [])
        sublist = item.get("sublist")
        if sublist:
            sub_lines = _list_items_merged_with_sublists(sublist.get("items") or [], indent=indent + 1)
            if sub_lines:
                text += "\n" + "\n".join(sub_lines)
        lines.append(text)
    return lines


def _list_derived_lines(blocks: list[dict]) -> list[str]:
    """One line per top-level item from raw content blocks - shared by
    Business Rules (task-26) and Non-Functional Requirements (task-27),
    both of which read an Azure field that's normally a plain bullet list
    and turn each item into its own ID'd row. Walks "list" blocks directly
    via _list_items_merged_with_sublists (so an item's own nested
    sub-bullets stay attached to IT, not split into spurious rows of their
    own) instead of going through blocks_to_plain_text, which has no
    concept of "this nested item belongs to that other line" once
    everything is flattened. Non-list blocks (plain paragraph, heading,
    table, code) fall back to the same one-entry-each behavior
    blocks_to_plain_text uses for them, since only lists have this
    parent/sub-item ambiguity.
    """
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "list":
            lines.extend(_list_items_merged_with_sublists(block.get("items") or []))
        elif block_type in ("text", "heading"):
            text = _runs_to_text(block.get("runs") or [])
            if text:
                lines.append(text)
        elif block_type == "code":
            text = block.get("text") or ""
            if text:
                lines.append(text)
        elif block_type == "table":
            lines.extend(
                " | ".join(_runs_to_text(cell) for cell in row) for row in block.get("rows") or []
            )
    return lines


def _story_business_rules(story: dict) -> list[tuple[str, str]]:
    """Business Rules for one User Story (backlog task-26), sourced from
    its "Requirement" tab - matched by label (see _matching_content_section_blocks
    - the exact Azure field name is unconfirmed, per docs/srs-content-mapping-spec.md).

    Per the spec, this is an either/or at the whole-list level, not decided
    line by line: if EVERY line already carries an explicit ID (e.g.
    "BR-001: ..."), those IDs are extracted via regex and used as-is. If
    even one line doesn't - the tell that this is just an ordinary,
    unlabeled bullet list - every line gets a GENERATED id instead
    (BRL-001, BRL-002, ...), scoped to just this one story: numbering
    restarts at 001 for every story, never continues across stories.

    A rule's own nested sub-bullets (see _list_items_merged_with_sublists)
    stay folded into that same rule's line rather than becoming their own
    (spurious) rules, and rather than being lost.

    Returns [] if the story has no matching Requirement-tab content at all.
    """
    blocks = _matching_content_section_blocks(story, _REQUIREMENT_TAB_LABEL_RE)
    if not blocks:
        return []
    lines = [line.strip() for line in _list_derived_lines(blocks) if line.strip()]
    if not lines:
        return []

    matches = [_EXPLICIT_ITEM_ID_RE.match(line) for line in lines]
    if all(matches):
        return [(m.group(1).strip(), m.group(2).strip()) for m in matches]  # type: ignore[union-attr]

    return [(f"BRL-{i:03d}", line) for i, line in enumerate(lines, start=1)]


def _build_business_rules_table(scratch: Document, rules: list[tuple[str, str]]) -> None:
    """Rule ID / Business Rule, navy header - matches every other data
    table's styling in this document. Omitted entirely (no subheading, no
    empty table) when a story has no Requirement-tab content at all -
    unlike the manual-placeholder sections earlier in the document, there's
    no template default to fall back to here since this table never
    existed before task-25 built the story block it lives in.
    """
    if not rules:
        return
    scratch.add_paragraph("Business Rules").runs[0].bold = True
    table = scratch.add_table(rows=1 + len(rules), cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    header_row = table.rows[0]
    for col, text in enumerate(("Rule ID", "Business Rule")):
        cell = header_row.cells[col]
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _set_cell_shading(cell, NAVY_FILL)

    for row_idx, (rule_id, rule_text) in enumerate(rules, start=1):
        table.rows[row_idx].cells[0].text = rule_id
        table.rows[row_idx].cells[1].text = rule_text

    # Same 1:4 ID-column-to-text-column ratio as every other ID/description
    # table in this document (e.g. 2.3 Definitions, backlog task-18).
    _apply_dynamic_table_formatting(table, [USABLE_WIDTH_IN * 0.2, USABLE_WIDTH_IN * 0.8])
    scratch.add_paragraph()  # spacer, matches every other table in this document


# ---------------------------------------------------------------------------
# 6. Non-Functional Requirements (backlog task-27)
# ---------------------------------------------------------------------------

_NFR_ID_PREFIX = "NFR"
# Category is embedded in the source text right before the NFR's own
# description, separated by ":", "-", or "->" per docs/srs-content-mapping-spec.md
# (e.g. "Performance: Screen loads shall complete within X seconds.").
# Bounded to a short, plain leading phrase so this doesn't misfire on
# ordinary prose that happens to contain a colon/hyphen further into the
# sentence - if nothing that short-and-early matches, the whole line is
# left as the Requirement text with Category blank rather than guessed.
# The spec also allows a "highlighted" (e.g. bold-run) category with no
# punctuated separator at all - NOT handled here, since that needs the
# raw per-run formatting rather than plain text; see backlog TASK-31 (or a
# future follow-up) if a real org turns out to rely on that form instead.
_NFR_CATEGORY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /&]{1,29})\s*(?:->|:|-|–)\s*(\S.*)$", re.DOTALL)


def _parse_nfr_category(text: str) -> tuple[str, str]:
    """Splits one NFR line into (category, requirement) per _NFR_CATEGORY_RE,
    or ("", text) unchanged if no leading category-like prefix is found.
    """
    match = _NFR_CATEGORY_RE.match(text)
    if not match:
        return "", text
    return match.group(1).strip(), match.group(2).strip()


def _epic_nfr_marked_entries(lines: list[str]) -> list[list[str]] | None:
    """Groups a flat sequence of lines into [id, category, requirement]
    triples by treating any line that matches _EXPLICIT_ITEM_ID_RE as the
    START of a new NFR - every line up to (not including) the NEXT such
    marker line, or the end of the sequence, is that NFR's own requirement
    text.

    This is deliberately NOT based on distinguishing a "heading" block
    from a "text" block: the real shape observed in the first org tested
    (2026-09-03 follow-up) is an "<h3>NFR01 - Security</h3>" caption
    followed by one or more "<p>" description paragraphs - but genuine
    (non-Markdown) HTML input never produces "heading"-typed blocks in the
    first place (see html_to_blocks/_BlockExtractor's own docstring: a
    real HTML `<h3>` is deliberately treated as a plain caption paragraph,
    landing in the same "text" block type as what follows it, since
    that's also what an Azure image-caption heading like "Context
    Diagram" needs). "heading" blocks only ever come from Markdown-sourced
    fields. So the ID-prefix marker on the line's own text is the only
    reliable signal here, regardless of which block type produced it.

    A marker line's own remainder (after its ID) is treated as the
    Category ONLY when further lines follow it before the next marker
    (the heading-plus-paragraphs shape - the remainder is just "Security",
    the real text is in what follows). When nothing follows before the
    next marker (or the end), the marker line is assumed to carry
    category AND requirement together on that one line (the
    originally-assumed "ID: Category - requirement text" shape) and
    _parse_nfr_category is applied to split it further.

    Returns None if no line carries an explicit ID at all - the tell that
    this content isn't marker-delimited, so the caller should fall back to
    the "every line is its own NFR" treatment instead.
    """
    marker_indices = [i for i, line in enumerate(lines) if _EXPLICIT_ITEM_ID_RE.match(line)]
    if not marker_indices:
        return None

    entries: list[list[str]] = []
    for position, start in enumerate(marker_indices):
        end = marker_indices[position + 1] if position + 1 < len(marker_indices) else len(lines)
        match = _EXPLICIT_ITEM_ID_RE.match(lines[start])
        nfr_id = match.group(1).strip()  # type: ignore[union-attr]
        remainder = match.group(2).strip()  # type: ignore[union-attr]
        following = " ".join(lines[start + 1 : end]).strip()
        if following:
            category, requirement = remainder, following
        else:
            category, requirement = _parse_nfr_category(remainder)
        entries.append([nfr_id, category, requirement])
    return entries


def _epic_nfr_rows(epics: list[dict]) -> list[list[str]]:
    """6. Non-Functional Requirements table rows - backlog task-27: sourced
    from every Epic's own "Analysis" tab content, same
    explicit-ID-vs-generate either/or rule as Business Rules (task-26), but
    applied per-Epic (each Epic's own Analysis-tab content is independently
    judged - one Epic having explicit IDs doesn't force another Epic's
    unlabeled content to invent IDs that aren't there).

    Unlike Business Rules, which gets its own separate table per User
    Story (so generated IDs restart at 001 for every story), section 6 is
    ONE table for the whole document - so a GENERATED id here is a single
    counter that runs continuously across every Epic's own content, in
    Epic order, rather than resetting per Epic.
    """
    rows: list[list[str]] = []
    next_generated = 1
    for epic in epics:
        blocks = _matching_content_section_blocks(epic, _ANALYSIS_TAB_LABEL_RE)
        if not blocks:
            continue
        lines = [line.strip() for line in _list_derived_lines(blocks) if line.strip()]
        if not lines:
            continue

        marked_entries = _epic_nfr_marked_entries(lines)
        if marked_entries is not None:
            for nfr_id, category, requirement in marked_entries:
                rows.append([nfr_id, category, requirement, ""])
            continue

        # No line anywhere carries an explicit ID - an ordinary unlabeled
        # bullet list, so every line is its own generated NFR.
        for line in lines:
            category, requirement = _parse_nfr_category(line)
            rows.append([f"{_NFR_ID_PREFIX}-{next_generated:03d}", category, requirement, ""])
            next_generated += 1
    return rows


def _build_story_info_table(
    scratch: Document,
    *,
    story_text: str,
    story_id: str,
    epic_name: str,
    feature_name: str,
    entry_criteria: str,
    exit_criteria: str,
) -> None:
    """User Story text/ID and Epic/Feature name are directly known from the
    hierarchy already built by normalize_content. Entry/Exit Criteria are
    sourced from the story's own content_sections, matched by label (same
    unconfirmed-exact-field-name approach as Epic's Requirement Description
    - see _matching_content_section_text) - blank if no matching field was
    found on that story, not guessed. Persona Involved has no defined
    source anywhere in docs/srs-content-mapping-spec.md, so it's left
    blank - Business Rules and the rest of a full User Story block
    (Functionalities, Acceptance Criteria, UI Description, Data Dictionary)
    are separate, not-yet-scoped work (Business Rules specifically is
    backlog task-26).
    """
    table = scratch.add_table(rows=7, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for row, (label, value) in zip(
        table.rows,
        (
            ("User Story", story_text),
            ("User Story ID", story_id),
            ("Epic Name", epic_name),
            ("Feature Name", feature_name),
            ("Persona Involved", ""),
            ("Entry Criteria", entry_criteria),
            ("Exit Criteria", exit_criteria),
        ),
    ):
        label_cell, value_cell = row.cells
        label_cell.text = label
        for p in label_cell.paragraphs:
            for r in p.runs:
                r.bold = True
        _set_cell_shading(label_cell, ZEBRA_FILL)  # matches 1.1's label column (build_label_value_table)
        value_cell.text = value
    # Same 26%/74% label/value split as every other label-value table in
    # this document (e.g. 1.1, build_v21_template.py's build_label_value_table).
    _apply_dynamic_table_formatting(table, [USABLE_WIDTH_IN * 0.26, USABLE_WIDTH_IN * 0.74])
    scratch.add_paragraph()  # spacer, matches the spacing every other table in this document gets


def _build_section_5_body(scratch: Document, epics: list[dict]) -> None:
    """Epic ID: {name}" / "Feature: {name}" / "User Story {NNN}: {title}"
    headings, literally numbered "5.{epic}", "5.{epic}.{feature}" matching
    the template's own convention (backlog task-10) - not Word
    auto-numbering. User Story numbers increase monotonically across the
    WHOLE document (story_number is never reset per Feature or Epic).
    """
    story_number = 0
    for epic_idx, epic in enumerate(epics, start=1):
        scratch.add_paragraph(f"5.{epic_idx} Epic ID: {epic.get('title') or ''}", style="Heading 2")
        features = [c for c in epic.get("children") or [] if c.get("work_item_type") == "Feature"]
        for feature_idx, feature in enumerate(features, start=1):
            scratch.add_paragraph(f"5.{epic_idx}.{feature_idx} Feature: {feature.get('title') or ''}", style="Heading 3")
            for story in feature.get("children") or []:
                story_number += 1
                title = story.get("title") or ""
                scratch.add_paragraph(f"User Story {story_number:0{_STORY_NUMBER_WIDTH}d}: {title}", style="Heading 3")
                story_text = blocks_to_plain_text(story.get("description_blocks") or []) or title
                _build_story_info_table(
                    scratch,
                    story_text=story_text,
                    story_id=f"US-{story['azure_work_item_id']}",
                    epic_name=epic.get("title") or "",
                    feature_name=feature.get("title") or "",
                    entry_criteria=_matching_content_section_text(story, _ENTRY_CRITERIA_LABEL_RE),
                    exit_criteria=_matching_content_section_text(story, _EXIT_CRITERIA_LABEL_RE),
                )
                _build_business_rules_table(scratch, _story_business_rules(story))  # backlog task-26


def _apply_section_5(document: Document, context: dict) -> None:
    epics = _flatten_by_type(context.get("roots") or [], "Epic")
    if not epics:
        return  # no Azure data to replace it with - keep the template's own worked example

    heading_5 = _find_paragraph(document, "5. Functional Requirements")
    heading_6 = _find_paragraph(document, "6. Non-Functional Requirements")

    body = document.element.body
    to_remove = []
    collecting = False
    for child in body.iterchildren():
        if child is heading_5._p:
            collecting = True
            continue
        if child is heading_6._p:
            break
        if collecting:
            to_remove.append(child)
    for element in to_remove:
        body.remove(element)

    # Built in a throwaway, otherwise-blank Document() using python-docx's
    # normal add_paragraph()/add_table() APIs (which only ever append to
    # the END of a document body, so they can't be used to insert content
    # in the MIDDLE of the real one directly) - the paragraphs/tables this
    # produces are then moved into the real document, one element at a
    # time, right before the "6." heading. Styles are referenced here by
    # NAME ("Heading 2") but stored as an ID ("Heading2") - once an
    # element is physically moved into the real document, Word/LibreOffice
    # resolve that ID against the OWNING document's styles.xml (the real
    # template's, not this scratch one), so the transplanted content picks
    # up the template's actual heading colors/sizes correctly, not
    # python-docx's own blank-document defaults.
    scratch = Document()
    _build_section_5_body(scratch, epics)

    anchor = heading_6._p
    for element in list(scratch.element.body.iterchildren()):
        if element.tag == qn("w:sectPr"):
            continue
        anchor.addprevious(element)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_srs_document_v2(context: dict, minio) -> bytes:  # noqa: ARG001 - minio unused until sections 2-8 need embedded assets
    """The "Generate Formatted SRS" entry point - same call signature as
    `docx_builder.build_srs_document(context, minio)` so `render_docx` can
    call either interchangeably based on `context["template_version"]`.
    """
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"V2 template not found at {TEMPLATE_PATH} - was it packaged into the worker image?")

    document_metadata = context.get("document_metadata") or {}
    cover_page = _cover_page_from_metadata(document_metadata, context)
    header_top_right = _header_top_right_from(cover_page["module_name"])
    document_info = _document_info_from_metadata(document_metadata, cover_page)

    document = Document(str(TEMPLATE_PATH))

    update_cover_page(document, cover_page)
    update_header(document, header_top_right)
    _apply_section_2_3_placeholders(document, context)

    tables = document.tables
    fill_document_information_table(tables[0], document_info)  # 1.1
    blank_table_data_rows(tables[1])  # 1.2 Version/Revision History
    blank_table_data_rows(tables[2])  # 1.3 Internal Review and Approval Matrix
    blank_table_data_rows(tables[3])  # 1.4 Document Sign-Off
    _populate_definitions_table(tables[4], context.get("v2_definitions"))  # 2.3 Definitions, Acronyms & Abbreviations
    # 3.4/3.6 - Epic-level Azure pull, read-only (backlog task-22). Tables
    # aren't affected by the paragraph-index shifts _apply_section_2_3_placeholders
    # has to worry about, so these can run any time relative to it.
    _populate_azure_sourced_table(
        tables[5], _collect_epic_content_lines(context, _ROLES_LABEL_RE), content_col=0
    )  # 3.4 User Roles / Personas
    _populate_azure_sourced_table(
        tables[6], _collect_epic_content_lines(context, _OUT_OF_SCOPE_LABEL_RE), content_col=1
    )  # 3.6 Out of Scope (has a leading SL column)
    # 4.1/4.2 - Epic/Feature-level Azure pull, read-only (backlog tasks 23,
    # 24). Every Epic/Feature in the sealed selection, not sampled - this
    # is a direct listing, not an LLM synthesis.
    roots = context.get("roots") or []
    epics = _flatten_by_type(roots, "Epic")
    _populate_epic_summary_table(tables[7], epics)  # 4.1 Epic / Functional Area Summary
    _populate_feature_list_table(tables[8], _flatten_by_type(roots, "Feature"))  # 4.2 Feature List

    # 5. Functional Requirements - backlog task-25. Replaces the template's
    # worked example with real Epic/Feature/User-Story content, which
    # changes how many tables section 5 itself contains - so everything
    # AFTER it must be located by content, not a fixed index, from here on.
    _apply_section_5(document, context)

    # 6. Non-Functional Requirements - backlog task-27. A single
    # document-wide table (not one per Epic/Story like section 5's), found
    # by its own header text for the same reason as everything below
    # section 5: its original index isn't stable once section 5's dynamic
    # content has resized the document.
    _populate_table_rows(_find_table_by_first_header_cell(document, "NFR ID"), _epic_nfr_rows(epics))

    # Found by its own header text, not a hardcoded index (tables[21] was
    # only ever valid while section 5 always had exactly the template's own
    # 2 worked-example tables - task-25 broke that assumption).
    blank_table_data_rows(_find_table_by_first_header_cell(document, "BR ID"))  # 9. Requirement Traceability Matrix

    buf = BytesIO()
    document.save(buf)
    return buf.getvalue()
