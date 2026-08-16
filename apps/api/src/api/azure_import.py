import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.azure_connections import create_pat_connection
from src.auth.sessions import require_user
from src.database.bootstrap import get_default_tenant, get_or_create_srs_project
from src.database.models import ImportJob, SnapshotWorkItem, SourceSnapshot, User
from src.database.session import get_db_session
from src.jobs.celery_bridge import enqueue_import_pipeline, enqueue_seal_pipeline
from srs_core.azure.url_parser import InvalidAzureDevOpsUrlError, parse_azure_devops_url

router = APIRouter(prefix="/import", tags=["import"])


class ParseUrlRequest(BaseModel):
    source_url: str


class ParseUrlResponse(BaseModel):
    org: str
    project: str
    team: str | None
    work_item_id: int | None
    backlog_level: str | None


@router.post("/parse-url", response_model=ParseUrlResponse)
async def parse_url(body: ParseUrlRequest) -> ParseUrlResponse:
    try:
        parsed = parse_azure_devops_url(body.source_url)
    except InvalidAzureDevOpsUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ParseUrlResponse(
        org=parsed.org,
        project=parsed.project,
        team=parsed.team,
        work_item_id=parsed.work_item_id,
        backlog_level=parsed.backlog_level,
    )


class DiscoverRequest(BaseModel):
    source_url: str
    pat: str


class DiscoverResponse(BaseModel):
    job_id: uuid.UUID
    srs_project_id: uuid.UUID


@router.post("/discover", response_model=DiscoverResponse)
async def discover(
    body: DiscoverRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> DiscoverResponse:
    try:
        parsed = parse_azure_devops_url(body.source_url)
    except InvalidAzureDevOpsUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    tenant = await get_default_tenant(db)
    project = await get_or_create_srs_project(
        db,
        tenant_id=tenant.id,
        azure_org=parsed.org,
        azure_project=parsed.project,
        azure_base_url=body.source_url,
        created_by_user_id=current_user.id,
    )
    connection = await create_pat_connection(
        db,
        tenant_id=tenant.id,
        srs_project_id=project.id,
        source_url=body.source_url,
        pat=body.pat,
        created_by_user_id=current_user.id,
    )

    import_job = ImportJob(
        tenant_id=tenant.id,
        srs_project_id=project.id,
        azure_connection_id=connection.id,
        status="queued",
        stage="queued",
        params={
            "source_url": body.source_url,
            "team": parsed.team,
            "backlog_level": parsed.backlog_level,
            "work_item_id": parsed.work_item_id,
        },
    )
    db.add(import_job)
    await db.flush()

    snapshot = SourceSnapshot(
        srs_project_id=project.id,
        import_job_id=import_job.id,
        source_url=body.source_url,
        status="creating",
        created_by_user_id=current_user.id,
    )
    db.add(snapshot)
    await db.flush()

    await db.commit()

    task_id = enqueue_import_pipeline(
        import_job_id=str(import_job.id), snapshot_id=str(snapshot.id), connection_id=str(connection.id)
    )
    import_job.celery_task_id = task_id
    db.add(import_job)
    await db.commit()

    return DiscoverResponse(job_id=import_job.id, srs_project_id=project.id)


class WorkItemNodeResponse(BaseModel):
    azure_work_item_id: int
    work_item_type: str
    title: str
    state: str
    is_selected: bool
    children: list["WorkItemNodeResponse"] = []


WorkItemNodeResponse.model_rebuild()


class DiscoveryTreeResponse(BaseModel):
    roots: list[WorkItemNodeResponse]
    unlinked_count: int
    snapshot_id: uuid.UUID | None


async def _load_job_and_snapshot(db: AsyncSession, job_id: uuid.UUID) -> tuple[ImportJob, SourceSnapshot | None]:
    job = await db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="import job not found")
    result = await db.execute(select(SourceSnapshot).where(SourceSnapshot.import_job_id == job_id))
    snapshot = result.scalar_one_or_none()
    return job, snapshot


def _build_tree(items: list[SnapshotWorkItem]) -> list[WorkItemNodeResponse]:
    by_id: dict[uuid.UUID, WorkItemNodeResponse] = {
        item.id: WorkItemNodeResponse(
            azure_work_item_id=item.azure_work_item_id,
            work_item_type=item.work_item_type,
            title=item.title,
            state=item.state,
            is_selected=item.is_selected,
            children=[],
        )
        for item in items
    }
    roots: list[WorkItemNodeResponse] = []
    for item in items:
        node = by_id[item.id]
        if item.parent_id is not None and item.parent_id in by_id:
            by_id[item.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.get("/{job_id}/tree", response_model=DiscoveryTreeResponse)
async def get_discovery_tree(job_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> DiscoveryTreeResponse:
    job, snapshot = await _load_job_and_snapshot(db, job_id)
    if snapshot is None:
        return DiscoveryTreeResponse(roots=[], unlinked_count=0, snapshot_id=None)

    result = await db.execute(
        select(SnapshotWorkItem)
        .where(SnapshotWorkItem.snapshot_id == snapshot.id)
        .order_by(SnapshotWorkItem.order_index, SnapshotWorkItem.azure_work_item_id)
    )
    items = list(result.scalars().all())
    roots = _build_tree(items)
    unlinked_count = len(job.warnings.get("unlinked_ids", [])) if job.warnings else 0

    return DiscoveryTreeResponse(roots=roots, unlinked_count=unlinked_count, snapshot_id=snapshot.id)


class SealRequest(BaseModel):
    selected_azure_ids: list[int] | None = None


class SealResponse(BaseModel):
    snapshot_id: uuid.UUID
    job_id: uuid.UUID


@router.post("/{job_id}/seal", response_model=SealResponse)
async def seal_snapshot(
    job_id: uuid.UUID, body: SealRequest, db: AsyncSession = Depends(get_db_session)
) -> SealResponse:
    job, snapshot = await _load_job_and_snapshot(db, job_id)
    if snapshot is None:
        raise HTTPException(status_code=409, detail="discovery has not produced a snapshot yet")
    if snapshot.status != "creating":
        raise HTTPException(status_code=409, detail=f"snapshot is '{snapshot.status}', expected 'creating'")

    if body.selected_azure_ids is not None:
        selected: set[int] = set(body.selected_azure_ids)
        result = await db.execute(select(SnapshotWorkItem).where(SnapshotWorkItem.snapshot_id == snapshot.id))
        for item in result.scalars().all():
            item.is_selected = item.azure_work_item_id in selected
        await db.commit()

    task_id = enqueue_seal_pipeline(
        import_job_id=str(job.id), snapshot_id=str(snapshot.id), connection_id=str(job.azure_connection_id)
    )
    job.celery_task_id = task_id
    db.add(job)
    await db.commit()

    return SealResponse(snapshot_id=snapshot.id, job_id=job.id)
