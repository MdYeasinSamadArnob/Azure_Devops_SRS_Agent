from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import GenerationJob, ImportJob
from src.database.session import get_db_session
from src.sse.job_events import stream_job_events

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    stage: str
    progress_percent: int
    error_message: str | None = None


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db_session)) -> JobResponse:
    import_job = await db.get(ImportJob, job_id)
    if import_job is not None:
        return JobResponse(
            id=str(import_job.id),
            job_type="import",
            status=import_job.status,
            stage=import_job.stage,
            progress_percent=import_job.progress_percent,
            error_message=import_job.error_message,
        )

    generation_job = await db.get(GenerationJob, job_id)
    if generation_job is not None:
        return JobResponse(
            id=str(generation_job.id),
            job_type="generate",
            status=generation_job.status,
            stage=generation_job.stage,
            progress_percent=generation_job.progress_percent,
            error_message=generation_job.error_message,
        )

    raise HTTPException(status_code=404, detail="job not found")


@router.get("/{job_id}/events")
async def get_job_events(
    job_id: str, request: Request, db: AsyncSession = Depends(get_db_session)
) -> StreamingResponse:
    last_event_id = request.headers.get("last-event-id")
    return StreamingResponse(
        stream_job_events(db, job_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
