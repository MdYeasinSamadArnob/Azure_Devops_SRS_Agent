"""IMPORT job chain: AUTHENTICATING -> DISCOVERING_FIELDS -> FETCHING_HIERARCHY
-> FETCHING_WORK_ITEMS, then (on seal) DOWNLOADING_ASSETS -> CREATING_SNAPSHOT
-> COMPLETED.

Split into two Celery entry points because a human selection step sits
between hierarchy discovery and sealing: `run_import` populates a draft,
unsealed snapshot for the user to review/select from; `run_seal` (Increment 3)
downloads assets for the final selection and seals it.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from srs_core.azure.client import AzureDevOpsAuthError, AzureDevOpsClient, HierarchyResult, WorkItemNode
from srs_core.db.models import Asset, ImportJob, SnapshotRelation, SnapshotWorkItem, SourceSnapshot, SrsProject
from srs_core.enums import BUCKET_SOURCE_ASSETS
from srs_core.parsing.custom_fields import extract_content_fields
from srs_core.parsing.html_images import extract_embedded_images

from src.celery_app import celery_app
from src.db import session_scope
from src.progress import mark_failed, mark_failed_unless_retrying, report_stage
from src.tasks.asset_pipeline import DEFAULT_DOWNLOAD_CONCURRENCY, DownloadJob, build_download_jobs, run_download_job
from src.tasks.connections import resolve_pat

logger = logging.getLogger(__name__)


async def _discover(
    org: str,
    project: str,
    pat: str,
    *,
    team: str | None,
    backlog_level: str | None,
    work_item_id: int | None,
) -> HierarchyResult:
    """Resolves a correctly-scoped root set first, then does a bounded BFS
    from there — never a project-wide scan. A project can span many teams
    and thousands of work items; only the team/backlog actually requested
    (or the single work item linked) is ever fetched.
    """
    client = AzureDevOpsClient(org, project, pat)
    try:
        await client.validate_access()

        if work_item_id is not None:
            root_ids = [work_item_id]
        elif team and backlog_level:
            backlog_id = await client.resolve_backlog_id(team, backlog_level)
            root_ids = await client.get_backlog_root_ids(team, backlog_id)
        elif team:
            # No explicit backlog level in the URL — default to the team's
            # top-most portfolio backlog (Azure returns levels top-to-bottom).
            backlogs = await client.list_team_backlogs(team)
            if not backlogs:
                raise ValueError(f"team '{team}' has no backlog levels configured")
            root_ids = await client.get_backlog_root_ids(team, backlogs[0]["id"])
        else:
            raise ValueError(
                "the URL must reference a specific team/backlog "
                "(e.g. .../_backlogs/backlog/{team}/{level}) or a single work item — "
                "importing an entire project is not supported"
            )

        if not root_ids:
            return HierarchyResult(roots=[], unlinked_ids=[], warnings=["no work items found at the requested scope"])

        return await client.fetch_hierarchy_from_roots(root_ids)
    finally:
        await client.aclose()


# The numeric field Azure Boards itself sorts a backlog by (lower = higher
# priority = appears first) — verified live against this org: ascending
# StackRank exactly matched the "Order" column shown in the Azure Boards
# backlog view. The field's reference name varies by process template
# (Scrum/CMMI use StackRank, some Agile templates use BacklogPriority
# instead) — checked in priority order, not hardcoded to one org's template.
_BACKLOG_ORDER_FIELDS = ("Microsoft.VSTS.Common.StackRank", "Microsoft.VSTS.Common.BacklogPriority")
_ORDER_INDEX_MAX = 2_147_483_647  # order_index is a 32-bit column; clamp rather than risk an overflow error


def _order_index_for(fields: dict) -> int:
    for field_name in _BACKLOG_ORDER_FIELDS:
        rank = fields.get(field_name)
        if isinstance(rank, (int, float)):
            return min(int(rank), _ORDER_INDEX_MAX)
    # No rank field on this item (e.g. some Task-level items don't carry
    # one) — sorts after every ranked sibling; ties break on azure_work_item_id.
    return _ORDER_INDEX_MAX


def _persist_tree(
    session: Session, snapshot_id: uuid.UUID, roots: list[WorkItemNode], *, org: str, project: str
) -> None:
    """Two-pass insert: create every row first, then wire up parent_id once
    every node has a generated primary key to point at.
    """
    azure_id_to_pk: dict[int, uuid.UUID] = {}
    all_nodes: list[WorkItemNode] = []
    seen_azure_ids: set[int] = set()

    def collect(node: WorkItemNode) -> None:
        # Defensive dedup: root-detection can only guarantee no duplicates
        # under well-formed Azure relation data — this is the backstop if it
        # ever isn't, so one malformed project can't crash the whole import.
        if node.azure_id in seen_azure_ids:
            return
        seen_azure_ids.add(node.azure_id)
        all_nodes.append(node)
        for child in node.children:
            collect(child)

    for root in roots:
        collect(root)

    for node in all_nodes:
        fields = node.fields
        row = SnapshotWorkItem(
            snapshot_id=snapshot_id,
            azure_work_item_id=node.azure_id,
            work_item_type=node.work_item_type,
            title=node.title,
            state=node.state,
            parent_azure_work_item_id=node.parent_azure_id,
            area_path=fields.get("System.AreaPath"),
            iteration_path=fields.get("System.IterationPath"),
            revision=fields.get("Rev", 1) if isinstance(fields.get("Rev", 1), int) else 1,
            description_html=fields.get("System.Description"),
            acceptance_criteria=(
                {"html": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")}
                if fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")
                else None
            ),
            tags={"raw": fields.get("System.Tags")} if fields.get("System.Tags") else None,
            priority=str(fields.get("Microsoft.VSTS.Common.Priority", "")) or None,
            order_index=_order_index_for(fields),
            raw_fields=fields,
            azure_url=f"https://dev.azure.com/{org}/{project}/_workitems/edit/{node.azure_id}",
            is_selected=True,
        )
        session.add(row)
        session.flush()
        azure_id_to_pk[node.azure_id] = row.id

    for node in all_nodes:
        if node.parent_azure_id is not None and node.parent_azure_id in azure_id_to_pk:
            row = session.get(SnapshotWorkItem, azure_id_to_pk[node.azure_id])
            row.parent_id = azure_id_to_pk[node.parent_azure_id]
            session.add(row)
            session.add(
                SnapshotRelation(
                    snapshot_id=snapshot_id,
                    source_azure_id=node.parent_azure_id,
                    target_azure_id=node.azure_id,
                    relation_type="System.LinkTypes.Hierarchy-Forward",
                )
            )


@celery_app.task(
    name="src.tasks.import_pipeline.run_import",
    bind=True,
    max_retries=3,
    # A real request against this org's backlog hit a transient Azure
    # DevOps error that succeeded immediately on manual retry with the
    # identical request — worth a few automatic attempts with backoff
    # before surfacing failure to the user.
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def run_import(self, import_job_id: str, snapshot_id: str, connection_id: str) -> dict:
    with session_scope() as session:
        try:
            job = session.get(ImportJob, import_job_id)
            if job is None:
                raise ValueError(f"import job {import_job_id} not found")
            params = job.params or {}

            report_stage(session, job_id=import_job_id, job_type="import", stage="authenticating", status="running")
            pat, org, project = resolve_pat(session, connection_id)

            report_stage(session, job_id=import_job_id, job_type="import", stage="discovering_fields")
            # Custom field discovery is Phase 2 — Phase 1 uses the fixed field
            # set read directly off each work item batch response.

            report_stage(session, job_id=import_job_id, job_type="import", stage="fetching_hierarchy")
            try:
                hierarchy = asyncio.run(
                    _discover(
                        org,
                        project,
                        pat,
                        team=params.get("team"),
                        backlog_level=params.get("backlog_level"),
                        work_item_id=params.get("work_item_id"),
                    )
                )
            except AzureDevOpsAuthError as exc:
                mark_failed(session, job_id=import_job_id, job_type="import", error_message=str(exc))
                return {"status": "failed", "reason": "auth"}
            except ValueError as exc:
                mark_failed(session, job_id=import_job_id, job_type="import", error_message=str(exc))
                return {"status": "failed", "reason": "invalid_scope"}

            report_stage(session, job_id=import_job_id, job_type="import", stage="fetching_work_items")
            _persist_tree(session, uuid.UUID(snapshot_id), hierarchy.roots, org=org, project=project)

            job.warnings = {"unlinked_ids": hierarchy.unlinked_ids, "messages": hierarchy.warnings}
            job.status = "completed"
            job.stage = "fetching_work_items"
            session.add(job)

            report_stage(
                session,
                job_id=import_job_id,
                job_type="import",
                stage="fetching_work_items",
                status="completed",
                message="discovery complete — awaiting selection and seal",
            )
            return {"status": "completed", "roots": len(hierarchy.roots)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_import failed for job %s", import_job_id)
            mark_failed_unless_retrying(self, session, job_id=import_job_id, job_type="import", error_message=str(exc))
            raise


async def _download_attachments_for_selection(
    session: Session,
    *,
    org: str,
    project: str,
    pat: str,
    tenant_id: uuid.UUID,
    srs_project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    selected_items: list[SnapshotWorkItem],
) -> list[dict]:
    """Discovers every image for the selected items — formal attachments AND
    <img> tags embedded directly in description/acceptance-criteria HTML —
    then downloads them all CONCURRENTLY (bounded semaphore) rather than one
    at a time. This is an I/O-bound workload (many small HTTP round-trips),
    so asyncio concurrency is what actually speeds it up; the MinIO upload
    itself is offloaded to a thread per-job so it can't stall the others.
    """
    client = AzureDevOpsClient(org, project, pat)
    try:
        raw_items = await client.get_work_items_batch([item.azure_work_item_id for item in selected_items])
        raw_by_azure_id = {raw["id"]: raw for raw in raw_items}

        jobs: list[tuple[DownloadJob, SnapshotWorkItem]] = []
        for item in selected_items:
            raw = raw_by_azure_id.get(item.azure_work_item_id)
            if raw is None:
                continue
            fields = raw.get("fields", {})
            # Scan every HTML-bearing field for embedded <img> tags — not
            # just Description/AcceptanceCriteria. Custom process templates
            # (ERD, Class Diagram, Context/Container/Deployment Diagram,
            # Database Design, ...) very often hold the actual architecture
            # diagrams, and hardcoding two field names would silently drop
            # them for this org (and any other org with a different
            # customized process).
            html_sources = [fields.get("System.Description"), fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")]
            html_sources += [cf.value for cf in extract_content_fields(fields)]
            embedded_images = [
                ref for html in html_sources for ref in extract_embedded_images(html, azure_org=org)
            ]
            for job in build_download_jobs(item.id, raw_item=raw, embedded_images=embedded_images):
                jobs.append((job, item))

        if not jobs:
            return []

        semaphore = asyncio.Semaphore(DEFAULT_DOWNLOAD_CONCURRENCY)
        async with httpx.AsyncClient(auth=("", pat)) as download_client:
            results = await asyncio.gather(
                *[
                    run_download_job(
                        job,
                        http_client=download_client,
                        semaphore=semaphore,
                        tenant_id=tenant_id,
                        srs_project_id=srs_project_id,
                        snapshot_id=snapshot_id,
                    )
                    for job, _item in jobs
                ]
            )

        # Session mutation happens here, sequentially, back on the main
        # coroutine — never inside the concurrent download tasks themselves.
        manifest: list[dict] = []
        for result in results:
            asset = Asset(
                tenant_id=tenant_id,
                srs_project_id=srs_project_id,
                snapshot_id=snapshot_id,
                snapshot_work_item_id=result["snapshot_work_item_id"],
                asset_kind="source_attachment",
                bucket=BUCKET_SOURCE_ASSETS,
                object_key=result["object_key"] or f"failed/{uuid.uuid4()}",
                content_type=result["content_type"] or "application/octet-stream",
                byte_size=result["byte_size"],
                original_filename=result["original_filename"],
                source_url=result["source_url"],
                azure_relation_type=result["azure_relation_type"],
                sha256_hash=result["sha256_hash"],
                download_status=result["status"],
            )
            session.add(asset)
            session.flush()
            if result["status"] == "completed":
                manifest.append(
                    {"asset_id": str(asset.id), "bucket": asset.bucket, "object_key": asset.object_key, "sha256": asset.sha256_hash}
                )
        return manifest
    finally:
        await client.aclose()


@celery_app.task(
    name="src.tasks.import_pipeline.run_seal",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_jitter=True,
)
def run_seal(self, import_job_id: str, snapshot_id: str, connection_id: str) -> dict:
    with session_scope() as session:
        try:
            snapshot = session.get(SourceSnapshot, snapshot_id)
            if snapshot is None:
                raise ValueError(f"snapshot {snapshot_id} not found")
            if snapshot.status != "creating":
                raise ValueError(f"snapshot {snapshot_id} is '{snapshot.status}', expected 'creating'")

            project = session.get(SrsProject, snapshot.srs_project_id)
            tenant_id = project.tenant_id

            report_stage(session, job_id=import_job_id, job_type="import", stage="downloading_assets", status="running")
            pat, org, azure_project = resolve_pat(session, connection_id)

            result = session.execute(
                select(SnapshotWorkItem).where(
                    SnapshotWorkItem.snapshot_id == uuid.UUID(snapshot_id),
                    SnapshotWorkItem.is_selected.is_(True),
                )
            )
            selected_items = list(result.scalars().all())

            manifest_entries = asyncio.run(
                _download_attachments_for_selection(
                    session,
                    org=org,
                    project=azure_project,
                    pat=pat,
                    tenant_id=tenant_id,
                    srs_project_id=snapshot.srs_project_id,
                    snapshot_id=uuid.UUID(snapshot_id),
                    selected_items=selected_items,
                )
            )

            report_stage(session, job_id=import_job_id, job_type="import", stage="creating_snapshot")
            snapshot.status = "validating"
            snapshot.manifest = {
                "assets": manifest_entries,
                "work_item_hash": hashlib.sha256(
                    "|".join(sorted(str(item.azure_work_item_id) for item in selected_items)).encode()
                ).hexdigest(),
            }
            snapshot.root_work_item_ids = [
                item.azure_work_item_id for item in selected_items if item.parent_id is None
            ]
            session.add(snapshot)
            session.flush()

            snapshot.status = "sealed"
            snapshot.sealed_at = datetime.now(timezone.utc)
            session.add(snapshot)

            report_stage(
                session,
                job_id=import_job_id,
                job_type="import",
                stage="completed",
                status="completed",
                message="snapshot sealed",
            )
            return {"status": "sealed", "assets": len(manifest_entries)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_seal failed for job %s", import_job_id)
            # Only give up on the snapshot (and mark the job failed) on the
            # FINAL attempt — a retry might still succeed, and flipping the
            # snapshot to 'failed' now would need it re-created from
            # scratch instead of just re-running the seal.
            if self.request.retries >= (self.max_retries or 0):
                snap = session.get(SourceSnapshot, snapshot_id)
                if snap is not None and snap.status == "creating":
                    snap.status = "failed"
                    session.add(snap)
                    session.commit()
            mark_failed_unless_retrying(self, session, job_id=import_job_id, job_type="import", error_message=str(exc))
            raise
