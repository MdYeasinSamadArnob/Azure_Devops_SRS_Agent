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
from docx.shared import Inches, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph
from srs_core.rendering.html_text import blocks_to_plain_text

from src.tasks.docx_builder import _render_blocks, resolve_document_title

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

    Defensive against a `table` narrower than `rows`' own column count
    (backlog task-38: a real production IndexError, traced to a caller
    matching the wrong, differently-shaped table - see
    _find_table_by_header_row and _named_subsection_blocks' foreign-table
    boundary check for the actual fixes to how that happens) - extra
    values beyond what the table actually has columns for are silently
    dropped rather than crashing the whole generation job over one
    mismatched table.
    """
    if not rows:
        blank_table_data_rows(table)
        return

    data_rows = table.rows[1:]
    for i, values in enumerate(rows):
        row = data_rows[i] if i < len(data_rows) else table.add_row()
        for col, value in enumerate(values):
            if col >= len(row.cells):
                logger.warning(
                    "_populate_table_rows: row has %d values but table only has %d columns - dropping the rest",
                    len(values), len(row.cells),
                )
                break
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
#
# Re-measured 2026-09-03 (backlog task-32) after build_v21_template.py's
# add_guidance() became a no-op - removing the template's 24 "Guidance: ..."
# authoring-hint paragraphs (a separate fix, at the template's own source
# rather than by pattern-matching arbitrary text at generation time) shifted
# every one of these indices down. Re-confirm again if that builder script's
# section 2/3 structure changes further.
# ---------------------------------------------------------------------------

PARA_2_1_PURPOSE = 32
PARA_2_2_SCOPE = 34
# 2.4's 4 sample bullet paragraphs (backlog task-19) - REMOVING 3 of them
# shifts every later paragraph index down by 3, so anything below index 41
# (namely 3.1 at 50, 3.2 at 52) MUST be read/written before this range is
# touched.
PARA_2_4_REFERENCES_FIRST = 38
PARA_2_4_REFERENCES_COUNT = 4
PARA_3_1_SOLUTION_OVERVIEW = 50
PARA_3_2_PROCESS_OVERVIEW = 52
# 3.3/3.5 (backlog task-34) and 3.4/3.6 (TABLES - indices 5/6 in
# document.tables) are no longer hardcoded-index paragraphs at all - 3.3/3.5
# are now located by heading TEXT (see _replace_section_body) since their
# per-Epic-grouped content has no fixed length to reserve a PARA_* count
# for, and 3.4/3.6 are handled alongside the other tables in
# build_srs_document_v2 instead of here.


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
# Also matches "Epic Purpose" as an alternate real-world field label
# (2026-09-06, real Epic 118802) - that org's "Custom.EpicPurpose" field
# holds no epic-purpose narrative at all; its ENTIRE content is the
# Attribute/Description persona table (Persona, Role in Epic, Primary
# Objective, Key Activities, ...), the same shape task-35 already expected
# for User Persona - just sitting under a field name that gives no hint of
# that. Same class of field-name/content mismatch as _ANALYSIS_TAB_LABEL_RE
# needing "non functional" (task-27) and _REQUIREMENT_TAB_LABEL_RE needing
# "business rule(s)".
_ROLES_LABEL_RE = re.compile(r"role|persona|epic.{0,3}purpose", re.IGNORECASE)
# Deliberately just "assumption" (backlog task-34), NOT "assumption|constraint"
# - if an org keeps Assumptions and Constraints as two SEPARATE fields, this
# must not also match the Constraints-only one; per user direction
# (2026-09-03), only Assumptions belongs in 3.5. If instead an org combines
# both into one "Assumptions and Constraints" field, this still finds it
# (the label still contains "assumption") - _epic_assumptions_blocks then
# does a best-effort CONTENT-level split to drop the Constraints portion.
_ASSUMPTIONS_LABEL_RE = re.compile(r"assumption", re.IGNORECASE)
# "Out of Scope" has 4 characters (" of ") between "out" and "scope" - a
# {0,3} bound here was a real bug caught in testing: it silently matched
# nothing against the template's own field label. {0,8} covers that plus
# reasonable variants ("Out-of-Scope", "Out Of  Scope").
_OUT_OF_SCOPE_LABEL_RE = re.compile(r"out.{0,8}scope", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 3.3-3.6 - per-Epic grouped, native-shape rendering (backlog task-34/35,
# replacing task-22's flat-merged-list/fixed-table approach entirely)
#
# All four are narrative sections where, with multiple Epics selected, a
# single list/table merging every Epic's own content together loses which
# item belongs to which Epic. Each gets its own "Epic - [Name]:" group
# instead, located by heading TEXT (not a hardcoded paragraph index - see
# _replace_section_body) since a per-Epic group's length varies with however
# much content that one Epic actually has - and each Epic's own content is
# rendered in whatever native shape Azure actually has it in (a numbered
# list, or one of several different real table shapes), not forced into a
# fixed set of columns the template happened to ship as a worked example.
# ---------------------------------------------------------------------------


def _replace_section_body(document: Document, start_heading_text: str, end_heading_text: str, build_fn) -> None:
    """Removes every paragraph/table between (not including) the heading
    `start_heading_text` and the heading `end_heading_text`, then inserts
    freshly built content right before `end_heading_text` - the same
    scratch-document-transplant technique _apply_section_5 established (see
    its own docstring: python-docx's add_paragraph()/add_table() only ever
    append to the END of a document, so new content is built in a throwaway
    Document() and each of its top-level body elements is moved into the
    real one via addprevious()).

    Locating by heading TEXT rather than a hardcoded paragraph index means
    this is immune to every earlier section's own dynamic-length edits, and
    never needs re-measuring the way a hardcoded PARA_* index would if the
    template's layout ever changes (see backlog task-32's index-re-measuring
    follow-up, which this technique avoids repeating for 3.3/3.5 going
    forward).

    `build_fn(scratch: Document)` populates the scratch document using its
    normal add_paragraph()/add_table() API.
    """
    start_heading = _find_paragraph(document, start_heading_text)
    end_heading = _find_paragraph(document, end_heading_text)

    body = document.element.body
    to_remove = []
    collecting = False
    for child in body.iterchildren():
        if child is start_heading._p:
            collecting = True
            continue
        if child is end_heading._p:
            break
        if collecting:
            to_remove.append(child)
    for element in to_remove:
        body.remove(element)

    scratch = Document()
    build_fn(scratch)

    anchor = end_heading._p
    for element in list(scratch.element.body.iterchildren()):
        if element.tag == qn("w:sectPr"):
            continue
        anchor.addprevious(element)


# A short, standalone marker line acting as an internal section boundary
# within a bigger multi-topic field - backlog task-35 (2026-09-03 real-data
# report, Epic 118802): Dependencies/User Roles/Assumptions/Out of Scope
# turned out NOT to be dedicated custom fields at all. Each Epic's own
# standard Description field ("Details" tab) and the same custom field
# already matched for section 6's NFRs ("Analysis" tab, backlog task-27)
# both turned out to be ONE long document internally divided into many
# named subsections via short standalone lines - "Dependencies", "Out of
# Scope", "User Persona", "Assumptions", but ALSO others we don't target
# ("B. Cheque Collection Rules", "Integration Requirements", "Business
# Process Diagram", numbered "FRxx." functional-requirement lines) - so a
# marker has to be recognized generically (short, no sentence-ending
# punctuation), not just by matching our own known keyword list, or the
# NEXT unrelated subsection wouldn't be recognized as the end boundary of
# the one we DO want.
_SECTION_MARKER_MAX_LENGTH = 60

# A table whose own header row starts with "NFR" is section 6's own
# content (backlog task-38's real production crash) - NEVER swept into
# Dependencies/User Roles/Assumptions/Out of Scope even if it's positioned
# right after one of their own marker lines with nothing else in between
# (table/list blocks are otherwise invisible to _is_section_marker_block's
# text-based marker detection, since _block_marker_text only handles
# "text"/"heading" block types - a genuine table has no such text to
# check). This matters more than a merely-misplaced Dependencies/Roles/
# Out-of-Scope table would: section 6's own lookup
# (_find_table_by_header_row) indexes into whatever it finds by a FIXED
# column count, so a misplaced NFR-shaped table ending up somewhere else
# isn't just a display glitch - it's a hard crash for the WHOLE
# generation job once section 6 grabs the wrong, differently-shaped table
# instead of its own.
_NFR_TABLE_HEADER_RE = re.compile(r"^nfr", re.IGNORECASE)


def _block_marker_text(block: dict) -> str:
    if block.get("type") in ("text", "heading"):
        return _runs_to_text(block.get("runs") or []).strip()
    return ""


def _is_section_marker_block(block: dict) -> bool:
    text = _block_marker_text(block)
    if not text or len(text) > _SECTION_MARKER_MAX_LENGTH:
        return False
    return not text.rstrip().endswith((".", ":", ";", ","))


def _table_header_first_cell_text(block: dict) -> str:
    rows = block.get("rows") or []
    if not rows or not rows[0]:
        return ""
    return _runs_to_text(rows[0][0]).strip()


def _is_foreign_table_block(block: dict) -> bool:
    """A table that belongs to a DIFFERENT, specific recognized section
    (currently: section 6's NFR table, by its "NFR..." header) regardless
    of which subsection is currently being collected - see
    _NFR_TABLE_HEADER_RE's own comment for why this one case matters more
    than a merely-misplaced table (backlog task-38's real production
    crash). Only tables are checked (not lists) since the confirmed leak,
    and the only downstream consumer that indexes by a fixed column
    position, both involve a table.
    """
    return block.get("type") == "table" and bool(_NFR_TABLE_HEADER_RE.match(_table_header_first_cell_text(block)))


def _named_subsection_blocks(blocks: list[dict], target_pattern: re.Pattern[str]) -> list[dict]:
    """Extracts the blocks belonging to ONE named subsection (e.g.
    "Dependencies", "Out of Scope", "Assumptions", "User Persona") from
    inside a bigger field's own blocks (see _SECTION_MARKER_MAX_LENGTH's
    comment above for why real Azure content needs this at all).

    Finds the FIRST block whose own text matches `target_pattern` AND
    looks like a section-marker line (_is_section_marker_block), then
    collects every block after it up to the NEXT marker-like block
    (whatever subsection THAT one starts, known or not) OR a foreign table
    (_is_foreign_table_block - a table/list block is otherwise invisible
    to the marker check above, so this is the only thing that stops a
    misplaced NFR table from being vacuumed into whatever's being
    collected here) or the end of the field, whichever comes first.
    Returns [] if no such marker is found.
    """
    for i, block in enumerate(blocks):
        text = _block_marker_text(block)
        if text and target_pattern.search(text) and _is_section_marker_block(block):
            collected: list[dict] = []
            for later in blocks[i + 1 :]:
                if _is_section_marker_block(later) or _is_foreign_table_block(later):
                    break
                collected.append(later)
            return collected
    return []


def _epic_details_subsection_blocks(epic: dict, target_pattern: re.Pattern[str]) -> list[dict]:
    """Dependencies (3.3) / Out of Scope (3.6) - backlog task-35: both live
    as named subsections inside the Epic's own standard Description field
    (the "Details" tab), found via description_blocks directly rather than
    content_sections (which deliberately excludes System.Description - see
    srs_core.parsing.custom_fields' own _EXPLICITLY_HANDLED). Falls back to
    matching a whole DEDICATED field by its own label (backlog task-22's
    original approach) if no such subsection is found there, in case a
    different org really does keep one of these as its own separate field.
    """
    found = _named_subsection_blocks(epic.get("description_blocks") or [], target_pattern)
    if found:
        return found
    return _matching_content_section_blocks(epic, target_pattern)


def _epic_analysis_subsection_blocks(epic: dict, target_pattern: re.Pattern[str]) -> list[dict]:
    """User Roles/Personas (3.4) / Assumptions (3.5) - backlog task-35:
    both live as named subsections inside the SAME "Analysis tab" custom
    field already matched for section 6's NFRs (_ANALYSIS_TAB_LABEL_RE,
    backlog task-27), not a dedicated field of their own. Same
    dedicated-field fallback as _epic_details_subsection_blocks.
    """
    analysis_blocks = _matching_content_section_blocks(epic, _ANALYSIS_TAB_LABEL_RE)
    found = _named_subsection_blocks(analysis_blocks, target_pattern)
    if found:
        return found
    return _matching_content_section_blocks(epic, target_pattern)


def _render_blocks_tightly(scratch: Document, blocks: list[dict], minio, *, assets: list[dict] | None = None) -> None:
    """Wraps docx_builder._render_blocks, then strips the default
    per-paragraph space-after (backlog task-39) off every paragraph it just
    added - the V2.1 template's own w:docDefaults gives EVERY paragraph a
    10pt space-after with no distinction between "the next paragraph starts
    a new logical block" (where that gap is exactly right - see every
    heading-to-table transition elsewhere in this document) and "the next
    paragraph is still part of THIS same flowing block" (where it reads as
    an oversized, unintended gap - confirmed via a real screenshot of a
    Functionalities block mixing short narrative lines with bullet lists,
    each stacking its own 10pt gap on top of the others'). The heading
    paragraph before this content and the spacer paragraph after it (added
    separately by the caller) keep their own default spacing, since THAT
    gap - between this whole block and whatever comes next - is the one
    actually wanted; only what _render_blocks itself adds is tightened.
    """
    start_index = len(scratch.paragraphs)
    _render_blocks(scratch, blocks, minio=minio, assets=assets or [], used_object_keys=set())
    for paragraph in scratch.paragraphs[start_index:]:
        paragraph.paragraph_format.space_after = Pt(0)


def _build_epic_grouped_body(scratch: Document, epics: list[dict], get_blocks, minio) -> None:
    """Shared per-Epic-grouped, native-Azure-shape-preserving renderer for
    3.3/3.4/3.5/3.6 (backlog task-34/35) - one "Epic - [Name]:" bold
    paragraph per Epic followed by that Epic's own matching content
    (`get_blocks(epic)`), rendered as-is (list stays a list, table stays a
    table) via docx_builder._render_blocks rather than flattened to plain
    bullets. "[Empty]" (no Epic heading) if there's no Azure data at all -
    never leaves the template's own bracketed sample text in a generated
    document.
    """
    any_content = False
    for epic in epics:
        blocks = get_blocks(epic)
        if not blocks:
            continue
        any_content = True
        heading = scratch.add_paragraph()
        heading.add_run(f"Epic - {epic.get('title') or ''}:").bold = True
        _render_blocks_tightly(scratch, blocks, minio)
    if not any_content:
        scratch.add_paragraph("[Empty]", style="List Bullet")


def _apply_dependencies_section(document: Document, epics: list[dict], minio) -> None:
    """3.3 Dependencies with Other Modules / Systems - backlog task-34/35."""
    _replace_section_body(
        document,
        "3.3 Dependencies with Other Modules / Systems",
        "3.4 User Roles / Personas",
        lambda scratch: _build_epic_grouped_body(
            scratch, epics, lambda e: _epic_details_subsection_blocks(e, _DEPENDENCIES_LABEL_RE), minio
        ),
    )


def _apply_roles_section(document: Document, epics: list[dict], minio) -> None:
    """3.4 User Roles / Personas - backlog task-35: was a fixed-column
    table (Role/Persona | Responsibility | Decision Authority) that never
    matched what Azure actually has (an Attribute | Description "User
    Persona" table) - reworked to the same per-Epic-grouped, native-shape
    approach as 3.3/3.5, replacing that table entirely rather than leaving
    it sitting empty alongside the real content.
    """
    _replace_section_body(
        document,
        "3.4 User Roles / Personas",
        "3.5 Assumptions and Constraints",
        lambda scratch: _build_epic_grouped_body(
            scratch, epics, lambda e: _epic_analysis_subsection_blocks(e, _ROLES_LABEL_RE), minio
        ),
    )


def _apply_assumptions_section(document: Document, epics: list[dict], minio) -> None:
    """3.5 Assumptions and Constraints - backlog task-34/35: only the
    Assumptions portion (Constraints, if the same field ever has its own
    marker for it, is dropped - see _named_subsection_blocks stopping at
    the next marker-like line either way)."""
    _replace_section_body(
        document,
        "3.5 Assumptions and Constraints",
        "3.6 Out of Scope",
        lambda scratch: _build_epic_grouped_body(
            scratch, epics, lambda e: _epic_analysis_subsection_blocks(e, _ASSUMPTIONS_LABEL_RE), minio
        ),
    )


def _apply_out_of_scope_section(document: Document, epics: list[dict], minio) -> None:
    """3.6 Out of Scope - backlog task-35: was a fixed-column table
    (SL | Item | Description) that never matched what Azure actually has
    (an ID | Out of Scope Item | Description table) - reworked to the same
    per-Epic-grouped, native-shape approach as the rest of this section.
    """
    _replace_section_body(
        document,
        "3.6 Out of Scope",
        "4. Feature Catalogue",
        lambda scratch: _build_epic_grouped_body(
            scratch, epics, lambda e: _epic_details_subsection_blocks(e, _OUT_OF_SCOPE_LABEL_RE), minio
        ),
    )


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
# Story-level, "Requirement" tab (backlog task-36) - a dedicated field
# (Custom.PersonaInvolved), not embedded in Business Rules' own field.
_PERSONA_INVOLVED_LABEL_RE = re.compile(r"persona", re.IGNORECASE)
# Story-level, "Requirement" tab (backlog task-36) - also a dedicated field
# (Custom.Functionalities), separate from Business Rules.
_FUNCTIONALITIES_LABEL_RE = re.compile(r"functionalit", re.IGNORECASE)
# Story-level, "UI and UX" tab (backlog task-37) - a dedicated field holding
# a UI mockup/wireframe image, matching the original template's own
# "[UI Screenshot / Wireframe]" worked-example placeholder for this exact
# spot in a User Story block.
_UI_DESCRIPTION_LABEL_RE = re.compile(r"ui.{0,5}desc", re.IGNORECASE)
# Story-level, "WireFrame" tab (backlog task-40) - a dedicated field
# (Custom.DataDictionary), rendered under its own "Data Dictionary" heading
# (relabeled 2026-09-06 - previously folded under "UI Description" with no
# label of its own) - not forced into any predefined table columns.
_DATA_DICTIONARY_LABEL_RE = re.compile(r"data.{0,5}dict", re.IGNORECASE)
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
    template. Any edit that inserts or removes paragraphs (2.4's trim)
    shifts every later paragraph's real position. Processing bottom-to-top
    means that by the time any given index is used, everything AFTER it in
    the document has already been finalized (so a later shift can't matter
    - that section is done), and nothing BEFORE it has been touched yet (so
    ITS index is still the original, correct one). Processing in document
    order, as earlier revisions of this function did, is what let a
    similar bug slip through once already (see backlog task-19's notes) -
    keep this order if more sections are added here.

    3.3-3.6 (backlog task-34/35) are no longer here - they're now
    heading-text-anchored (_apply_dependencies_section/_apply_roles_section/
    _apply_assumptions_section/_apply_out_of_scope_section, called
    separately in build_srs_document_v2), not index-based, since their
    per-Epic-grouped content has no fixed paragraph/table count to reserve.
    """
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


def _find_table_by_header_row(document: Document, header_texts: tuple[str, ...]) -> object:
    """Like _find_table_by_first_header_cell, but verifies the WHOLE header
    row, not just its first cell - backlog task-38: a real production crash
    (a differently-shaped table's own first cell coincidentally matching
    another section's lookup text - see _named_subsection_blocks' new
    foreign-table boundary check, which is the actual fix for how that
    happens in the first place; this is the second, independent layer that
    keeps the lookup itself safe even if some OTHER leak this doesn't
    anticipate ever gets through) means matching just the first cell isn't
    a safe enough signal for a table whose column count another function
    is about to index into by a fixed position.
    """
    for table in document.tables:
        if not table.rows:
            continue
        cells = table.rows[0].cells
        if len(cells) == len(header_texts) and tuple(c.text.strip() for c in cells) == header_texts:
            return table
    raise RuntimeError(f"expected a table with header row {header_texts!r} not found in the V2 template - did its structure change?")


def _find_table_after_paragraph(document: Document, paragraph: Paragraph) -> object:
    """The first table appearing after `paragraph` in document order - a
    table located by STRUCTURAL position (right after a known heading)
    rather than a fixed tables[] index (backlog task-34: no longer stable
    for anything at or after 3.4, once 3.5's Assumptions section can
    insert a variable number of its own tables ahead of them - a real bug
    this caught: 3.6's table was being silently blanked as a stand-in for
    a table that no longer existed at that index) or by header-cell text
    (3.6's own header starts with "SL", the same first-cell text 1.2 and
    1.3 both use, so a header-text lookup alone would be ambiguous here).
    """
    found_anchor = False
    for element in document.element.body.iterchildren():
        if element is paragraph._p:
            found_anchor = True
            continue
        if found_anchor and element.tag == qn("w:tbl"):
            return Table(element, document)
    raise RuntimeError(f"expected a table after paragraph {paragraph.text!r} - did the V2 template structure change?")


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


def _build_labeled_blocks_section(
    scratch: Document, heading_text: str, blocks: list[dict], minio, *, assets: list[dict] | None = None
) -> None:
    """Functionalities / Acceptance Criteria / UI Description (backlog
    tasks 36/37) - a bold heading (same convention as
    _build_business_rules_table's "Business Rules" label) followed by the
    source content in its own native Azure shape (list stays a list, table
    stays a table, embedded image stays an image) via docx_builder's
    _render_blocks, same principle as 3.3-3.6 (backlog task-34/35).
    Omitted entirely (no empty heading) when there's no matching content -
    same as Business Rules, there's no template default to fall back to
    since this never existed in the template before task-25 built the
    story block it lives in.

    `assets` defaults to [] (Functionalities/Acceptance Criteria are text
    content, never images) - UI Description passes the story's own real
    assets list so its embedded picture can actually be matched and
    downloaded (see docx_builder._render_image_block).
    """
    if not blocks:
        return
    scratch.add_paragraph(heading_text).runs[0].bold = True
    _render_blocks_tightly(scratch, blocks, minio, assets=assets)
    scratch.add_paragraph()  # spacer, matches every other block in this story section


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


# An NFR's own explicit ID always starts with "NFR" (every real example
# seen: NFR01-NFR08) - deliberately stricter than the generic
# _EXPLICIT_ITEM_ID_RE (any letter-prefix + digits), because that generic
# pattern also matches "FR09." (a Functional - not Non-Functional -
# Requirement line living in the SAME field, see _epic_nfr_blocks) and
# would wrongly treat it as an NFR marker, dragging everything up to the
# next marker (once, an entire unrelated "Assumptions" table) in as its
# "description".
_NFR_ITEM_ID_RE = re.compile(r"^\s*(nfr[-_ ]?\d{1,4})\s*[:.\-–]\s*(.+)$", re.IGNORECASE | re.DOTALL)
_NFR_SECTION_HEADING_RE = re.compile(r"non.{0,3}functional", re.IGNORECASE)


def _epic_nfr_blocks(epic: dict) -> list[dict]:
    """Scopes down to just the NFR-related portion of the Epic's
    Analysis-tab field (backlog task-35 follow-up, 2026-09-03 real-data
    report): that field turned out to hold OTHER named subsections too
    (Business Process Diagram, User Persona, Functional Requirements,
    Assumptions - see _epic_analysis_subsection_blocks), not just NFRs, so
    processing the WHOLE field as NFR content (task-27's original
    assumption - correct for the one epic tested then, which had nothing
    else in that field) picks up unrelated content as fake NFRs once a
    real field has more than just NFRs in it.

    Two real shapes observed: (a) a field that's ENTIRELY NFR content, no
    wrapper heading, starting directly with "NFR01 - ..." (Epic 118798);
    (b) a field with other named subsections mixed in, where NFR content
    might have its own "Non Functional Requirements" wrapper heading, OR
    might just be identifiable by its own "NFR<n>" marker lines with no
    wrapper at all. Handles both: finds the first NFR-looking marker
    (a wrapper heading match, OR an "NFR<n>" item's own line), then
    collects from there, treating any OTHER marker-like line as the end
    boundary UNLESS it's itself another "NFR<n>" line (which continues the
    section rather than ending it - each NFR item's own heading line would
    otherwise look like the boundary for the item before it).
    """
    blocks = _matching_content_section_blocks(epic, _ANALYSIS_TAB_LABEL_RE)
    if not blocks:
        return []

    start = None
    for i, block in enumerate(blocks):
        text = _block_marker_text(block)
        if not text:
            continue
        if _NFR_SECTION_HEADING_RE.search(text) and _is_section_marker_block(block):
            start = i + 1  # skip the wrapper heading itself - not NFR content
            break
        if _NFR_ITEM_ID_RE.match(text):
            start = i  # no wrapper heading - this item's own line IS the start
            break
    if start is None:
        return []

    collected: list[dict] = []
    for block in blocks[start:]:
        text = _block_marker_text(block)
        if text and _is_section_marker_block(block) and not _NFR_ITEM_ID_RE.match(text):
            break
        collected.append(block)
    return collected


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
        blocks = _epic_nfr_blocks(epic)
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
    persona_involved: str,
    entry_criteria: str,
    exit_criteria: str,
) -> None:
    """User Story text/ID and Epic/Feature name are directly known from the
    hierarchy already built by normalize_content. Persona Involved/Entry/
    Exit Criteria are sourced from the story's own content_sections,
    matched by label (same unconfirmed-exact-field-name approach as Epic's
    Requirement Description - see _matching_content_section_text) - blank
    if no matching field was found on that story, not guessed. Business
    Rules/Functionalities/Acceptance Criteria are separate, appended after
    this table (backlog tasks 26/36); UI Description/Data Dictionary remain
    not-yet-scoped work.
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
            ("Persona Involved", persona_involved),
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


def _build_section_5_body(scratch: Document, epics: list[dict], minio) -> None:
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
                    persona_involved=_matching_content_section_text(story, _PERSONA_INVOLVED_LABEL_RE),
                    entry_criteria=_matching_content_section_text(story, _ENTRY_CRITERIA_LABEL_RE),
                    exit_criteria=_matching_content_section_text(story, _EXIT_CRITERIA_LABEL_RE),
                )
                _build_business_rules_table(scratch, _story_business_rules(story))  # backlog task-26
                # Functionalities / Acceptance Criteria (backlog task-36) -
                # right after Business Rules, matching the observed real
                # story layout. Functionalities is a dedicated Requirement-
                # tab field (Custom.Functionalities); Acceptance Criteria is
                # Azure's own STANDARD field, already split out separately
                # by generate_pipeline.py (never part of content_sections -
                # see custom_fields.py's own _EXPLICITLY_HANDLED).
                _build_labeled_blocks_section(
                    scratch,
                    "Functionalities",
                    _matching_content_section_blocks(story, _FUNCTIONALITIES_LABEL_RE),
                    minio,
                )
                _build_labeled_blocks_section(
                    scratch, "Acceptance Criteria", story.get("acceptance_criteria_blocks") or [], minio
                )
                # UI Description (backlog task-37) - the "UI and UX" tab's
                # mockup/wireframe image, matching the original template's
                # own "[UI Screenshot / Wireframe]" worked-example spot.
                # Needs the story's own REAL assets (not the default []
                # Functionalities/Acceptance Criteria use) so the UI
                # mockup's embedded picture can actually be matched and
                # downloaded.
                _build_labeled_blocks_section(
                    scratch,
                    "UI Description",
                    _matching_content_section_blocks(story, _UI_DESCRIPTION_LABEL_RE),
                    minio,
                    assets=story.get("assets"),
                )
                # Data Dictionary (backlog task-40, relabeled 2026-09-06) -
                # the "WireFrame" tab's field table, under its OWN "Data
                # Dictionary" heading (previously folded silently under "UI
                # Description" with no label of its own - per user
                # direction, give it a distinct heading so the pulled
                # table's origin is clear), in its own native table shape
                # (not forced into any predefined columns).
                _build_labeled_blocks_section(
                    scratch,
                    "Data Dictionary",
                    _matching_content_section_blocks(story, _DATA_DICTIONARY_LABEL_RE),
                    minio,
                )


def _apply_section_5(document: Document, context: dict, minio) -> None:
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
    _build_section_5_body(scratch, epics, minio)

    anchor = heading_6._p
    for element in list(scratch.element.body.iterchildren()):
        if element.tag == qn("w:sectPr"):
            continue
        anchor.addprevious(element)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_srs_document_v2(context: dict, minio) -> bytes:
    """The "Generate Formatted SRS" entry point - same call signature as
    `docx_builder.build_srs_document(context, minio)` so `render_docx` can
    call either interchangeably based on `context["template_version"]`.
    `minio` is passed through to 3.3-3.6's _render_blocks calls (image
    blocks in any of those fields, if any - see _build_epic_grouped_body).
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

    roots = context.get("roots") or []
    epics = _flatten_by_type(roots, "Epic")

    # 3.3-3.6 - Epic-level Azure pull, read-only (backlog task-34/35,
    # reworking task-22). Heading-text-anchored (see _replace_section_body),
    # not index-based, per-Epic-grouped, native-Azure-shape-preserving -
    # each pulls its own named subsection out of a bigger field (Details
    # tab's description_blocks for 3.3/3.6, the Analysis-tab field also
    # used for section 6's NFRs for 3.4/3.5 - see _epic_details_subsection_blocks/
    # _epic_analysis_subsection_blocks) rather than matching a dedicated
    # field by its own label - real Azure content (task-35) turned out to
    # cram all of this into one or two big fields, not separate ones.
    # Run before the table captures below since none of these touch a
    # PRE-EXISTING table element, but logically belong with the rest of
    # section 2/3.
    _apply_dependencies_section(document, epics, minio)  # 3.3 Dependencies with Other Modules / Systems
    _apply_roles_section(document, epics, minio)  # 3.4 User Roles / Personas
    _apply_assumptions_section(document, epics, minio)  # 3.5 Assumptions and Constraints (Assumptions only)
    _apply_out_of_scope_section(document, epics, minio)  # 3.6 Out of Scope

    tables = document.tables
    fill_document_information_table(tables[0], document_info)  # 1.1
    # 1.2/1.3/1.4 stay manually maintained (backlog task-7/13, unchanged) -
    # the app never auto-populates them from Azure/LLM data. What changed
    # (backlog task-33): they're no longer blanked either - left exactly as
    # loaded from the template, so the user gets the template's own
    # placeholder/example rows ([Name], V0.1, Business Analyst, Draft, ...)
    # to reference and edit, rather than a fully empty table.
    _populate_definitions_table(tables[4], context.get("v2_definitions"))  # 2.3 Definitions, Acronyms & Abbreviations
    # 4.1/4.2 - Epic/Feature-level Azure pull, read-only (backlog tasks 23,
    # 24). Found by structural position (the table right after each one's
    # own heading), NOT a tables[] index - 3.3-3.6 above can each now
    # insert a variable number of their own tables ahead of these, which
    # would otherwise silently shift every index after them (a real bug
    # caught in testing: a downstream table was being blanked as a
    # stand-in for a table that had moved to a different index). Nor by
    # header-cell text alone - some of these tables share the same
    # first-cell text as an unrelated earlier table.
    _populate_epic_summary_table(
        _find_table_after_paragraph(document, _find_paragraph(document, "4.1 Epic / Functional Area Summary")), epics
    )  # 4.1 Epic / Functional Area Summary
    _populate_feature_list_table(
        _find_table_after_paragraph(document, _find_paragraph(document, "4.2 Feature List")),
        _flatten_by_type(roots, "Feature"),
    )  # 4.2 Feature List

    # 5. Functional Requirements - backlog task-25. Replaces the template's
    # worked example with real Epic/Feature/User-Story content, which
    # changes how many tables section 5 itself contains - so everything
    # AFTER it must be located by content, not a fixed index, from here on.
    _apply_section_5(document, context, minio)

    # 6. Non-Functional Requirements - backlog task-27. A single
    # document-wide table (not one per Epic/Story like section 5's), found
    # by its own header text for the same reason as everything below
    # section 5: its original index isn't stable once section 5's dynamic
    # content has resized the document.
    _populate_table_rows(
        _find_table_by_header_row(document, ("NFR ID", "Category", "Requirement", "Target / SLA")), _epic_nfr_rows(epics)
    )

    # 9. Requirement Traceability Matrix (RTM) stays manually maintained too
    # (backlog task-13/33, same as 1.2/1.3/1.4 above) - left exactly as
    # loaded from the template, keeping its own placeholder example rows.

    buf = BytesIO()
    document.save(buf)
    return buf.getvalue()
