import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.sessions import require_user
from src.database.models import GenerationJob, SourceSnapshot, User
from src.database.session import get_db_session
from src.jobs.celery_bridge import enqueue_generate_pipeline

router = APIRouter(prefix="/snapshots", tags=["generation"])


class DocumentMetadata(BaseModel):
    """The new SRS template's 1.1 Document Information table has 11 fields
    (see docs/srs-content-mapping-spec.md and backlog task-6) - a typed
    model here, rather than a bare dict[str, str], makes the field set
    self-documenting in the OpenAPI schema and catches a typo'd key at
    request-validation time instead of it silently vanishing into an
    unused dict entry. Every field is optional: none of them are required
    to start a generation, matching the "manual, fill in later" default
    the template itself uses for anything left blank.

    Not yet consumed by docx_builder.py's OLD template logic (only
    resolve_document_title's document_title fallback bridges the gap) -
    full 1.1-table population from these fields is backlog task-15's job,
    once the new template is ported into the real pipeline.
    """

    document_id: str | None = None
    module_code: str | None = None
    document_title: str | None = None
    document_owner: str | None = None
    related_brd: str | None = None
    date_created: str | None = None
    date_submitted: str | None = None
    document_status: str | None = None
    document_version: str | None = None
    classification: str | None = None
    review_cycle: str | None = None
    # Not one of the 1.1 table's 11 fields, but the new template's COVER
    # PAGE needs it (the old template has no equivalent field at all) -
    # discovered wiring this up for real, added here rather than in a
    # separate schema so the form has one dict to manage.
    client: str | None = None


class GenerateRequest(BaseModel):
    formats: list[str]
    document_metadata: DocumentMetadata | None = None
    # "legacy" (default) = the original org-template pipeline ("Generate
    # Document" button); "v2" = the new ERA_SRS_Template_V2.1 pipeline
    # ("Generate Formatted SRS" button). See backlog task-15.
    template_version: Literal["legacy", "v2"] = "legacy"


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

    # Downstream (job.params JSON column, Celery task args) all expect a
    # plain JSON-serializable dict, not a Pydantic model - and exclude_none
    # so an unfilled optional field doesn't show up as a literal "None"
    # string once it reaches docx_builder.py's `.get(...)` calls.
    document_metadata_dict = body.document_metadata.model_dump(exclude_none=True) if body.document_metadata else {}

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
        params={
            "formats": body.formats,
            "document_metadata": document_metadata_dict,
            "template_version": body.template_version,
        },
        created_by_user_id=current_user.id,
    )
    db.add(job)
    await db.commit()

    task_id = enqueue_generate_pipeline(
        generation_job_id=str(job.id),
        snapshot_id=str(snapshot.id),
        formats=body.formats,
        document_metadata=document_metadata_dict,
        template_version=body.template_version,
    )
    job.celery_task_id = task_id
    db.add(job)
    await db.commit()

    return GenerateResponse(job_id=job.id)
