"""GENERATE job chain: NORMALIZING_CONTENT -> RUNNING_LLM_RULES ->
RENDERING_DOCX -> CONVERTING_PDF -> VERIFYING_DOCUMENT -> COMPLETED.

Each stage is its OWN Celery task chained together (not one monolithic
function) specifically so `convert_pdf` can be routed to the isolated
`conversion` queue while everything else runs on `document` — a hung or
memory-heavy LibreOffice process must never be able to starve normalization
or DOCX rendering. Context is passed between tasks as a plain JSON-safe
dict (Celery chain results travel through the broker as messages).

The document body is built directly via python-docx (see docx_builder.py),
not docxtpl — see that module's docstring for why.
"""

import contextlib
import hashlib
import logging
import os
import signal
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from sqlalchemy import select
from srs_core.enums import BUCKET_GENERATED_DOCUMENTS
from srs_core.llm.adapter import get_default_adapter
from srs_core.parsing.custom_fields import extract_content_fields
from srs_core.rendering.html_text import blocks_to_plain_text, html_to_blocks
from srs_core.storage.minio_client import MinioClient, MinioSettings, generated_document_key

from src.celery_app import celery_app
from src.config import get_worker_settings
from src.db import session_scope
from src.progress import mark_failed, report_stage
from src.storage_helpers import upload_with_fallback
from src.tasks.docx_builder import build_srs_document

logger = logging.getLogger(__name__)

MAX_EPICS_IN_LLM_PROMPT = 25

# A fixed 120s budget regardless of document size was the root cause of PDF
# conversion "getting stuck" on large documents: a real live-generated DOCX
# for a single Epic's subtree (79 of 1,392 backlog items) was already
# 24.7MB, so a full-backlog document routinely exceeds a flat timeout.
# Base + a per-MB allowance, capped at a ceiling so a single pathological
# document can't hang a worker forever.
CONVERSION_BASE_TIMEOUT_SECONDS = 180
CONVERSION_SECONDS_PER_MB = 20
CONVERSION_MAX_TIMEOUT_SECONDS = 900


def _timeout_for_size(byte_size: int) -> int:
    size_mb = byte_size / (1024 * 1024)
    timeout = CONVERSION_BASE_TIMEOUT_SECONDS + int(size_mb * CONVERSION_SECONDS_PER_MB)
    return min(timeout, CONVERSION_MAX_TIMEOUT_SECONDS)


def _run_soffice_conversion(docx_path: Path, out_dir: str, profile_dir: Path, timeout_seconds: int) -> None:
    """Runs LibreOffice headless with an ISOLATED user-profile directory
    (`-env:UserInstallation=...`). Without this, every conversion in this
    container shares the same default LibreOffice profile/lock directory —
    reproduced live: a conversion killed on timeout leaves an orphaned
    `soffice.bin` holding that lock (soffice forks a child process; killing
    only the launcher, as plain `subprocess.run(..., timeout=...)` does,
    doesn't kill the child), so the NEXT conversion hangs waiting on the
    stale lock, itself times out, and the failure cascades — this is the
    actual mechanism behind PDF conversion "sometimes getting stuck".
    Launching in its own session (`start_new_session=True`) and killing the
    whole process GROUP on timeout prevents that orphan from ever existing.
    """
    cmd = [
        "soffice",
        f"-env:UserInstallation=file://{profile_dir}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        out_dir,
        str(docx_path),
    ]
    process = subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise RuntimeError(f"PDF conversion exceeded {timeout_seconds}s timeout") from None
    if process.returncode != 0:
        raise RuntimeError(f"soffice conversion failed: {stderr.decode(errors='replace')}")


def _get_minio_client() -> MinioClient:
    settings = get_worker_settings()
    return MinioClient(
        MinioSettings(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    )


def _build_hierarchy_tree(items: list[Any], assets_by_item: dict[str, list[dict]]) -> list[dict]:
    """Reconstructs the real Epic > Feature > Story > Task/Bug tree from
    each item's parent_id, scoped to only the SELECTED items. If a node's
    immediate parent isn't itself selected (a partial-selection edge case —
    e.g. the user kept a Story but excluded its Feature), the node becomes
    a root itself rather than silently disappearing.
    """
    nodes: dict[str, dict] = {}
    for item in items:
        # Custom process-template fields (ERD, Class Diagram, Business
        # Rules, Functional/Non-Functional Requirements, ...) hold real
        # requirement content this org's process captures outside the
        # standard Description/AcceptanceCriteria fields — discovered
        # generically so this isn't hardcoded to one org's field names.
        #
        # `html_to_blocks` (not the old flat `html_to_plain_text`) preserves
        # `<table>`/`<ul>`/`<ol>` structure — real fields like "Data
        # Dictionary" are genuine HTML tables, and flattening them to plain
        # text turned each row into a sparse few-word paragraph that the
        # template's justified "S Notes" style then stretched into
        # unreadable, widely-spaced text. Rendering each block with layout
        # that matches its actual shape (table/list/prose) is the fix.
        content_sections = [
            {"label": cf.label, "blocks": html_to_blocks(cf.value)}
            for cf in extract_content_fields(item.raw_fields or {})
        ]
        content_sections = [s for s in content_sections if s["blocks"]]

        nodes[str(item.id)] = {
            "azure_work_item_id": item.azure_work_item_id,
            "work_item_type": item.work_item_type,
            "title": item.title,
            "state": item.state,
            "description_blocks": html_to_blocks(item.description_html),
            "acceptance_criteria_blocks": html_to_blocks((item.acceptance_criteria or {}).get("html"))
            if item.acceptance_criteria
            else [],
            "content_sections": content_sections,
            "azure_url": item.azure_url or f"#work-item-{item.azure_work_item_id}",
            "assets": assets_by_item.get(str(item.id), []),
            "children": [],
            "_parent_id": str(item.parent_id) if item.parent_id else None,
        }

    roots: list[dict] = []
    for node in nodes.values():
        parent_id = node.pop("_parent_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


@celery_app.task(name="src.tasks.generate_pipeline.normalize_content", bind=True, max_retries=2)
def normalize_content(
    self, generation_job_id: str, snapshot_id: str, formats: list[str], document_metadata: dict[str, str] | None = None
) -> dict[str, Any]:
    from srs_core.db.models import Asset, GenerationJob, OrgBrandingSettings, SnapshotWorkItem, SourceSnapshot

    with session_scope() as session:
        try:
            snapshot = session.get(SourceSnapshot, snapshot_id)
            if snapshot is None:
                raise ValueError(f"snapshot {snapshot_id} not found")
            if snapshot.status != "sealed":
                raise ValueError(f"snapshot {snapshot_id} is '{snapshot.status}', expected 'sealed'")

            job = session.get(GenerationJob, generation_job_id)
            if job is None:
                raise ValueError(f"generation job {generation_job_id} not found")

            report_stage(
                session, job_id=generation_job_id, job_type="generate", stage="normalizing_content", status="running"
            )

            result = session.execute(
                select(SnapshotWorkItem)
                .where(SnapshotWorkItem.snapshot_id == snapshot.id, SnapshotWorkItem.is_selected.is_(True))
                .order_by(SnapshotWorkItem.order_index, SnapshotWorkItem.azure_work_item_id)
            )
            items = list(result.scalars().all())

            asset_result = session.execute(
                select(Asset).where(
                    Asset.snapshot_id == snapshot.id,
                    Asset.asset_kind == "source_attachment",
                    Asset.download_status == "completed",
                )
            )
            assets_by_item: dict[str, list[dict]] = {}
            for a in asset_result.scalars().all():
                if a.snapshot_work_item_id is not None:
                    # source_url is what lets docx_builder match a downloaded
                    # asset back to the specific <img> tag it came from, so an
                    # embedded diagram can render right after its own heading
                    # (e.g. "Context Diagram") instead of being batched at
                    # the end of the work item with no idea which was which.
                    assets_by_item.setdefault(str(a.snapshot_work_item_id), []).append(
                        {"bucket": a.bucket, "object_key": a.object_key, "source_url": a.source_url}
                    )

            roots = _build_hierarchy_tree(items, assets_by_item)

            # Org branding overrides — absent means "keep the template
            # defaults", so this is purely additive. Only a lightweight
            # {bucket, object_key} reference travels through the chain
            # (Celery messages are JSON, not a home for raw image bytes);
            # render_docx downloads the actual logo bytes right before
            # calling build_srs_document, same as every other embedded image.
            resolved_metadata = dict(document_metadata or {})
            branding_result = session.execute(
                select(OrgBrandingSettings).where(OrgBrandingSettings.tenant_id == job.tenant_id)
            )
            branding = branding_result.scalar_one_or_none()
            logo_override = None
            if branding is not None:
                if not resolved_metadata.get("footer_year") and branding.footer_year_default:
                    resolved_metadata["footer_year"] = branding.footer_year_default
                if branding.logo_asset_id is not None:
                    logo_asset = session.get(Asset, branding.logo_asset_id)
                    if logo_asset is not None:
                        logo_override = {"bucket": logo_asset.bucket, "object_key": logo_asset.object_key}

            return {
                "generation_job_id": generation_job_id,
                "snapshot_id": snapshot_id,
                "tenant_id": str(job.tenant_id),
                "srs_project_id": str(job.srs_project_id),
                "source_url": snapshot.source_url,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "formats": formats,
                "document_metadata": resolved_metadata,
                "logo_override": logo_override,
                "total_count": len(items),
                "roots": roots,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("normalize_content failed for job %s", generation_job_id)
            mark_failed(session, job_id=generation_job_id, job_type="generate", error_message=str(exc))
            raise


@celery_app.task(name="src.tasks.generate_pipeline.run_llm_rules", bind=True, max_retries=1)
def run_llm_rules(self, context: dict[str, Any]) -> dict[str, Any]:
    """Optional AI enhancement: a short, grounded Introduction section
    generated from the Epic list. Never fails the chain — a slow,
    unreachable, or misconfigured LLM must never block document generation;
    it just means the Introduction falls back to the deterministic default
    in docx_builder. Clearly marked as AI-generated in the rendered output
    per the "controlled enhancement" principle — it augments, never
    replaces, the SOURCE_EXTRACTED technical content (titles/IDs/state are
    always the raw Azure data, verbatim, everywhere in the document).
    """
    generation_job_id = context["generation_job_id"]
    context["ai_introduction"] = None

    with session_scope() as session:
        report_stage(session, job_id=generation_job_id, job_type="generate", stage="running_llm_rules")

    try:
        adapter = get_default_adapter()
        if adapter is None:
            logger.info("no LLM configured (MODEL_NAME unset) — skipping AI introduction")
            return context

        epics = [r for r in context["roots"] if r["work_item_type"] == "Epic"]
        source_items = (epics or context["roots"])[:MAX_EPICS_IN_LLM_PROMPT]
        if not source_items:
            return context

        bullet_lines = []
        for item in source_items:
            description_text = blocks_to_plain_text(item.get("description_blocks") or [])
            line = f"- {item['title']}: {description_text[:300]}"
            # This org's process template (and often others) puts real
            # requirement content in custom fields — Business Rules,
            # Functional/Non-Functional Requirements, etc. — not just the
            # standard Description field. Fold a short snippet of each into
            # the grounding so the introduction reflects that content too.
            for section in item.get("content_sections", [])[:5]:
                snippet = blocks_to_plain_text(section.get("blocks") or [])[:200]
                if snippet:
                    line += f"\n  {section['label']}: {snippet}"
            bullet_lines.append(line)
        prompt = (
            "The following are Epics from a software project's Azure DevOps backlog:\n\n"
            + "\n".join(bullet_lines)
            + "\n\nWrite a concise, professional 2-3 paragraph Introduction section for a "
            "Software Requirements Specification document, summarizing the overall purpose and "
            "scope of this system based ONLY on the epics listed above. Do not invent features "
            "not implied by the list. Do not use markdown formatting or headings — plain "
            "paragraphs only."
        )
        context["ai_introduction"] = adapter.complete(
            prompt,
            system="You are a technical writer producing a professional Software Requirements Specification document.",
            max_tokens=500,
        )
    except Exception:  # noqa: BLE001 — AI enhancement is always optional
        logger.warning("run_llm_rules failed, continuing without AI introduction", exc_info=True)

    return context


@celery_app.task(name="src.tasks.generate_pipeline.render_docx", bind=True, max_retries=2)
def render_docx(self, context: dict[str, Any]) -> dict[str, Any]:
    from srs_core.db.models import Asset, GeneratedDocument

    generation_job_id = context["generation_job_id"]
    with session_scope() as session:
        try:
            report_stage(session, job_id=generation_job_id, job_type="generate", stage="rendering_docx")

            minio = _get_minio_client()
            docx_bytes = build_srs_document(context, minio)

            generation_id = str(uuid.uuid4())
            docx_key = generated_document_key(
                context["tenant_id"], context["srs_project_id"], generation_id, "document.docx"
            )
            upload_with_fallback(
                minio,
                BUCKET_GENERATED_DOCUMENTS,
                docx_key,
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

            docx_asset = Asset(
                tenant_id=context["tenant_id"],
                srs_project_id=context["srs_project_id"],
                asset_kind="generated_document",
                bucket=BUCKET_GENERATED_DOCUMENTS,
                object_key=docx_key,
                sha256_hash=hashlib.sha256(docx_bytes).hexdigest(),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                byte_size=len(docx_bytes),
                original_filename="srs_document.docx",
                download_status="completed",
            )
            session.add(docx_asset)
            session.flush()
            session.add(
                GeneratedDocument(
                    generation_job_id=uuid.UUID(generation_job_id),
                    snapshot_id=uuid.UUID(context["snapshot_id"]),
                    generation_id=uuid.UUID(generation_id),
                    format="docx",
                    asset_id=docx_asset.id,
                )
            )

            context["generation_id"] = generation_id
            context["docx_bucket"] = BUCKET_GENERATED_DOCUMENTS
            context["docx_object_key"] = docx_key
            context.pop("roots")  # no longer needed downstream, keeps the chain payload small
            context.pop("ai_introduction", None)
            return context
        except Exception as exc:  # noqa: BLE001
            logger.exception("render_docx failed for job %s", generation_job_id)
            mark_failed(session, job_id=generation_job_id, job_type="generate", error_message=str(exc))
            raise


@celery_app.task(
    name="src.tasks.generate_pipeline.convert_pdf",
    bind=True,
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def convert_pdf(self, context: dict[str, Any]) -> dict[str, Any]:
    """Routed to the isolated `conversion` queue (see celery_app.py task_routes)
    — this is the only task in the chain that shells out to LibreOffice.
    A failure here must preserve the already-rendered DOCX and fail only
    this stage, not the whole GENERATE job.
    """
    from srs_core.db.models import Asset, GeneratedDocument

    generation_job_id = context["generation_job_id"]
    if "pdf" not in context["formats"]:
        return context

    with session_scope() as session:
        try:
            report_stage(session, job_id=generation_job_id, job_type="generate", stage="converting_pdf")

            minio = _get_minio_client()
            docx_bytes = minio.download_bytes(context["docx_bucket"], context["docx_object_key"])

            with tempfile.TemporaryDirectory() as tmp_dir:
                docx_path = Path(tmp_dir) / "document.docx"
                docx_path.write_bytes(docx_bytes)
                profile_dir = Path(tmp_dir) / "lo_profile"
                profile_dir.mkdir()
                timeout_seconds = _timeout_for_size(len(docx_bytes))
                logger.info(
                    "converting %.1fMB DOCX to PDF for job %s with a %ds timeout",
                    len(docx_bytes) / (1024 * 1024),
                    generation_job_id,
                    timeout_seconds,
                )
                _run_soffice_conversion(docx_path, tmp_dir, profile_dir, timeout_seconds)

                pdf_path = Path(tmp_dir) / "document.pdf"
                if not pdf_path.exists():
                    raise RuntimeError("soffice did not produce a PDF output file")
                pdf_bytes = pdf_path.read_bytes()

            pdf_key = generated_document_key(
                context["tenant_id"], context["srs_project_id"], context["generation_id"], "document.pdf"
            )
            upload_with_fallback(minio, BUCKET_GENERATED_DOCUMENTS, pdf_key, pdf_bytes, "application/pdf")

            pdf_asset = Asset(
                tenant_id=context["tenant_id"],
                srs_project_id=context["srs_project_id"],
                asset_kind="generated_document",
                bucket=BUCKET_GENERATED_DOCUMENTS,
                object_key=pdf_key,
                sha256_hash=hashlib.sha256(pdf_bytes).hexdigest(),
                content_type="application/pdf",
                byte_size=len(pdf_bytes),
                original_filename="srs_document.pdf",
                download_status="completed",
            )
            session.add(pdf_asset)
            session.flush()
            session.add(
                GeneratedDocument(
                    generation_job_id=uuid.UUID(generation_job_id),
                    snapshot_id=uuid.UUID(context["snapshot_id"]),
                    generation_id=uuid.UUID(context["generation_id"]),
                    format="pdf",
                    asset_id=pdf_asset.id,
                )
            )
            return context
        except Exception as exc:  # noqa: BLE001
            # Only THIS stage fails — the already-rendered/uploaded DOCX from
            # render_docx is untouched, matching the plan's Phase 1 acceptance
            # criterion that a failed PDF conversion preserves the DOCX.
            logger.exception("convert_pdf failed for job %s", generation_job_id)

            # soffice failures here are frequently transient resource
            # pressure (reproduced live: identical input alternated between
            # a clean abort and a hard SIGKILL depending on host memory
            # pressure at that moment) rather than a deterministic defect —
            # worth a couple of automatic retries before giving up, same as
            # the import pipeline's autoretry_for tasks. Only mark the whole
            # generation job "failed" on the final attempt; a retry might
            # still succeed.
            if self.request.retries < (self.max_retries or 0):
                report_stage(
                    session,
                    job_id=generation_job_id,
                    job_type="generate",
                    stage="converting_pdf",
                    status="running",
                    message=f"retrying after: {exc}",
                )
                # A manual self.retry() call does NOT inherit the decorator's
                # retry_backoff/retry_backoff_max — those only apply to
                # Celery's own automatic autoretry_for-triggered retries.
                # Without an explicit countdown here it falls back to
                # Task.default_retry_delay (180s) — reproduced live, an
                # unintended 3-minute wait per attempt. Computing it
                # explicitly keeps this consistent with the decorator's
                # intent (capped exponential backoff, ~30s max).
                countdown = min(30, 2**self.request.retries)
                raise self.retry(exc=exc, countdown=countdown) from exc

            report_stage(
                session,
                job_id=generation_job_id,
                job_type="generate",
                stage="converting_pdf",
                status="failed",
                message=str(exc),
            )
            from srs_core.db.models import GenerationJob

            job = session.get(GenerationJob, generation_job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = f"PDF conversion failed (DOCX preserved): {exc}"
                session.add(job)
                session.commit()  # must survive the raise below — see report_stage's commit for why
            raise


@celery_app.task(name="src.tasks.generate_pipeline.verify_document", bind=True, max_retries=1)
def verify_document(self, context: dict[str, Any]) -> dict[str, Any]:
    from srs_core.db.models import GenerationJob

    generation_job_id = context["generation_job_id"]
    with session_scope() as session:
        job = session.get(GenerationJob, generation_job_id)
        if job is not None and job.status == "failed":
            # convert_pdf already marked this failed and preserved the DOCX —
            # don't overwrite that terminal state with a false "completed".
            return context

        try:
            report_stage(session, job_id=generation_job_id, job_type="generate", stage="verifying_document")

            minio = _get_minio_client()
            docx_bytes = minio.download_bytes(context["docx_bucket"], context["docx_object_key"])
            DocxDocument(BytesIO(docx_bytes))  # raises if the DOCX is corrupt
            if not minio.object_exists(context["docx_bucket"], context["docx_object_key"]):
                raise RuntimeError("rendered DOCX missing from MinIO immediately after upload")

            report_stage(
                session,
                job_id=generation_job_id,
                job_type="generate",
                stage="completed",
                status="completed",
                message="generation complete",
            )
            return context
        except Exception as exc:  # noqa: BLE001
            logger.exception("verify_document failed for job %s", generation_job_id)
            mark_failed(session, job_id=generation_job_id, job_type="generate", error_message=str(exc))
            raise
