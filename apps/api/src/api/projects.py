import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.sessions import require_user
from src.database.models import GeneratedDocument, GenerationJob, SrsProject, User
from src.database.session import get_db_session

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectListItem(BaseModel):
    id: uuid.UUID
    name: str
    azure_org: str
    azure_project: str
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[ProjectListItem])
async def list_my_projects(
    db: AsyncSession = Depends(get_db_session), current_user: User = Depends(require_user)
) -> list[ProjectListItem]:
    result = await db.execute(
        select(SrsProject)
        .where(SrsProject.created_by_user_id == current_user.id)
        .order_by(SrsProject.updated_at.desc())
    )
    return [
        ProjectListItem(
            id=p.id,
            name=p.name,
            azure_org=p.azure_org,
            azure_project=p.azure_project,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in result.scalars().all()
    ]


class GeneratedDocumentItem(BaseModel):
    format: str
    asset_id: uuid.UUID


class GenerationHistoryItem(BaseModel):
    generation_job_id: uuid.UUID
    snapshot_id: uuid.UUID
    status: str
    error_message: str | None
    formats: list[str]
    document_metadata: dict[str, Any]
    created_at: datetime
    documents: list[GeneratedDocumentItem]


@router.get("/{project_id}/generations", response_model=list[GenerationHistoryItem])
async def list_project_generations(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> list[GenerationHistoryItem]:
    project = await db.get(SrsProject, project_id)
    if project is None or project.created_by_user_id != current_user.id:
        # 404, not 403 — don't confirm another user's project even exists.
        raise HTTPException(status_code=404, detail="project not found")

    result = await db.execute(
        select(GenerationJob).where(GenerationJob.srs_project_id == project_id).order_by(GenerationJob.created_at.desc())
    )
    jobs = list(result.scalars().all())
    if not jobs:
        return []

    # generation_id groups the docx+pdf pair from ONE generate run — never
    # overwritten by a later regeneration (see GeneratedDocument's
    # docstring) — this is what makes "version history" meaningful: every
    # past run's documents stay downloadable, not just the latest.
    doc_result = await db.execute(
        select(GeneratedDocument).where(GeneratedDocument.generation_job_id.in_([job.id for job in jobs]))
    )
    documents_by_job: dict[uuid.UUID, list[GeneratedDocument]] = {}
    for doc in doc_result.scalars().all():
        documents_by_job.setdefault(doc.generation_job_id, []).append(doc)

    return [
        GenerationHistoryItem(
            generation_job_id=job.id,
            snapshot_id=job.snapshot_id,
            status=job.status,
            error_message=job.error_message,
            formats=job.params.get("formats", []),
            document_metadata=job.params.get("document_metadata", {}),
            created_at=job.created_at,
            documents=[
                GeneratedDocumentItem(format=doc.format, asset_id=doc.asset_id)
                for doc in documents_by_job.get(job.id, [])
            ],
        )
        for job in jobs
    ]
