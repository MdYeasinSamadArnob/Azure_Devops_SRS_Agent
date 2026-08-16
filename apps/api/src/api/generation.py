import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.sessions import require_user
from src.database.models import GenerationJob, SourceSnapshot, User
from src.database.session import get_db_session
from src.jobs.celery_bridge import enqueue_generate_pipeline

router = APIRouter(prefix="/snapshots", tags=["generation"])


class GenerateRequest(BaseModel):
    formats: list[str]
    document_metadata: dict[str, str] | None = None


class GenerateResponse(BaseModel):
    job_id: uuid.UUID


@router.post("/{snapshot_id}/generate", response_model=GenerateResponse)
async def trigger_generation(
    snapshot_id: uuid.UUID,
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> GenerateResponse:
    if not body.formats or not set(body.formats).issubset({"docx", "pdf"}):
        raise HTTPException(status_code=422, detail="formats must be a non-empty subset of ['docx', 'pdf']")

    snapshot = await db.get(SourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    if snapshot.status != "sealed":
        raise HTTPException(status_code=409, detail=f"snapshot is '{snapshot.status}', generation requires 'sealed'")

    from src.database.models import SrsProject

    project = await db.get(SrsProject, snapshot.srs_project_id)
    if project is None:
        # snapshot.srs_project_id is a FK — this only happens if the data is
        # already inconsistent, not from any request the caller controls.
        raise HTTPException(status_code=500, detail="snapshot references a missing project")

    job = GenerationJob(
        tenant_id=project.tenant_id,
        srs_project_id=snapshot.srs_project_id,
        snapshot_id=snapshot.id,
        status="queued",
        stage="queued",
        params={"formats": body.formats, "document_metadata": body.document_metadata or {}},
        created_by_user_id=current_user.id,
    )
    db.add(job)
    await db.commit()

    task_id = enqueue_generate_pipeline(
        generation_job_id=str(job.id),
        snapshot_id=str(snapshot.id),
        formats=body.formats,
        document_metadata=body.document_metadata,
    )
    job.celery_task_id = task_id
    db.add(job)
    await db.commit()

    return GenerateResponse(job_id=job.id)
