import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import GeneratedDocument, SourceSnapshot
from src.database.session import get_db_session

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    status: str
    source_url: str
    sealed_at: str | None = None


@router.get("/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(snapshot_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)) -> SnapshotResponse:
    snapshot = await db.get(SourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return SnapshotResponse(
        id=snapshot.id,
        status=snapshot.status,
        source_url=snapshot.source_url,
        sealed_at=snapshot.sealed_at.isoformat() if snapshot.sealed_at else None,
    )


class GeneratedDocumentResponse(BaseModel):
    id: uuid.UUID
    format: str
    asset_id: uuid.UUID


@router.get("/{snapshot_id}/documents", response_model=list[GeneratedDocumentResponse])
async def list_documents(
    snapshot_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> list[GeneratedDocumentResponse]:
    result = await db.execute(select(GeneratedDocument).where(GeneratedDocument.snapshot_id == snapshot_id))
    return [
        GeneratedDocumentResponse(id=doc.id, format=doc.format, asset_id=doc.asset_id)
        for doc in result.scalars().all()
    ]
