import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import get_secret_box
from src.auth.sessions import require_user
from src.database.models import AzureConnection, User
from src.database.session import get_db_session
from srs_core.azure.url_parser import parse_azure_devops_url

router = APIRouter(prefix="/connections", tags=["connections"])


class CreateConnectionRequest(BaseModel):
    source_url: str
    pat: str


class ConnectionResponse(BaseModel):
    connection_id: uuid.UUID
    azure_org: str
    azure_project: str


async def create_pat_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    srs_project_id: uuid.UUID | None,
    source_url: str,
    pat: str,
    created_by_user_id: uuid.UUID | None = None,
) -> AzureConnection:
    """Encrypts the PAT immediately — the plaintext value never survives past this call."""
    parsed = parse_azure_devops_url(source_url)
    encrypted = get_secret_box().encrypt(pat)
    connection = AzureConnection(
        tenant_id=tenant_id,
        srs_project_id=srs_project_id,
        auth_type="pat",
        encrypted_pat=encrypted,
        azure_org=parsed.org,
        azure_project=parsed.project,
        created_by_user_id=created_by_user_id,
    )
    db.add(connection)
    await db.flush()
    return connection


@router.post("", response_model=ConnectionResponse)
async def create_connection(
    body: CreateConnectionRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> ConnectionResponse:
    from src.database.bootstrap import get_default_tenant

    tenant = await get_default_tenant(db)
    connection = await create_pat_connection(
        db,
        tenant_id=tenant.id,
        srs_project_id=None,
        source_url=body.source_url,
        pat=body.pat,
        created_by_user_id=current_user.id,
    )
    await db.commit()
    return ConnectionResponse(
        connection_id=connection.id, azure_org=connection.azure_org, azure_project=connection.azure_project
    )


class ConnectionListItem(BaseModel):
    id: uuid.UUID
    azure_org: str
    azure_project: str
    created_at: datetime


@router.get("", response_model=list[ConnectionListItem])
async def list_my_connections(
    db: AsyncSession = Depends(get_db_session), current_user: User = Depends(require_user)
) -> list[ConnectionListItem]:
    # Only org/project/created_at — the encrypted PAT (or any value derived
    # from it) is never returned here, same "never displayed again after
    # submission" principle the connection form already documents.
    result = await db.execute(
        select(AzureConnection)
        .where(AzureConnection.created_by_user_id == current_user.id)
        .order_by(AzureConnection.created_at.desc())
    )
    return [
        ConnectionListItem(id=c.id, azure_org=c.azure_org, azure_project=c.azure_project, created_at=c.created_at)
        for c in result.scalars().all()
    ]


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> None:
    connection = await db.get(AzureConnection, connection_id)
    if connection is None or connection.created_by_user_id != current_user.id:
        # 404, not 403 — don't confirm another user's connection even exists.
        raise HTTPException(status_code=404, detail="connection not found")
    await db.delete(connection)
    await db.commit()
