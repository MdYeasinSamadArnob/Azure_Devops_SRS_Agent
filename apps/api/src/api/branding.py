"""Org branding settings — the document logo and default footer copyright
year, overridable per tenant instead of only ever the org template's
baked-in ERA InfoTech branding. Absent/`logo_asset_id IS NULL` means "keep
using the template default" — this whole feature is purely additive.
"""

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from srs_core.enums import BUCKET_TEMPLATES, AssetKind
from srs_core.security.file_signature import sniff_content_type
from srs_core.storage.minio_client import MinioClient

from src.auth.sessions import require_user
from src.database.bootstrap import get_default_tenant
from src.database.models import Asset, OrgBrandingSettings, User
from src.database.session import get_db_session
from src.minio.deps import get_minio_client

router = APIRouter(prefix="/branding", tags=["branding"])

_ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024


class BrandingResponse(BaseModel):
    logo_asset_id: uuid.UUID | None
    footer_year_default: str | None


class UpdateBrandingRequest(BaseModel):
    footer_year_default: str | None = None


async def _get_or_create_settings(db: AsyncSession, tenant_id: uuid.UUID) -> OrgBrandingSettings:
    result = await db.execute(select(OrgBrandingSettings).where(OrgBrandingSettings.tenant_id == tenant_id))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = OrgBrandingSettings(tenant_id=tenant_id)
        db.add(settings)
        await db.flush()
    return settings


@router.get("", response_model=BrandingResponse)
async def get_branding(
    db: AsyncSession = Depends(get_db_session), _current_user: User = Depends(require_user)
) -> BrandingResponse:
    tenant = await get_default_tenant(db)
    settings = await _get_or_create_settings(db, tenant.id)
    return BrandingResponse(logo_asset_id=settings.logo_asset_id, footer_year_default=settings.footer_year_default)


@router.put("", response_model=BrandingResponse)
async def update_branding(
    body: UpdateBrandingRequest,
    db: AsyncSession = Depends(get_db_session),
    _current_user: User = Depends(require_user),
) -> BrandingResponse:
    tenant = await get_default_tenant(db)
    settings = await _get_or_create_settings(db, tenant.id)
    settings.footer_year_default = body.footer_year_default
    await db.commit()
    return BrandingResponse(logo_asset_id=settings.logo_asset_id, footer_year_default=settings.footer_year_default)


@router.post("/logo", response_model=BrandingResponse)
async def upload_logo(
    file: UploadFile,
    db: AsyncSession = Depends(get_db_session),
    minio: MinioClient = Depends(get_minio_client),
    current_user: User = Depends(require_user),
) -> BrandingResponse:
    body = await file.read()
    if len(body) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=422, detail=f"logo exceeds {_MAX_LOGO_BYTES} byte limit")

    content_type = sniff_content_type(body, file.filename or "logo.png", file.content_type)
    if content_type not in _ALLOWED_LOGO_TYPES:
        raise HTTPException(status_code=422, detail="logo must be a PNG or JPEG image")

    tenant = await get_default_tenant(db)
    asset_id = uuid.uuid4()
    extension = "png" if content_type == "image/png" else "jpg"
    object_key = f"branding/{tenant.id}/logo/{asset_id}.{extension}"

    try:
        minio.upload_bytes(BUCKET_TEMPLATES, object_key, body, content_type)
    except Exception as exc:  # noqa: BLE001 — object storage may genuinely be unreachable
        raise HTTPException(status_code=503, detail="could not reach object storage — try again shortly") from exc

    asset = Asset(
        id=asset_id,
        tenant_id=tenant.id,
        srs_project_id=None,
        asset_kind=AssetKind.TEMPLATE,
        bucket=BUCKET_TEMPLATES,
        object_key=object_key,
        sha256_hash=hashlib.sha256(body).hexdigest(),
        content_type=content_type,
        byte_size=len(body),
        original_filename=file.filename,
        download_status="completed",
    )
    db.add(asset)
    await db.flush()

    settings = await _get_or_create_settings(db, tenant.id)
    settings.logo_asset_id = asset.id
    await db.commit()

    return BrandingResponse(logo_asset_id=settings.logo_asset_id, footer_year_default=settings.footer_year_default)


@router.delete("/logo", response_model=BrandingResponse)
async def reset_logo(
    db: AsyncSession = Depends(get_db_session), _current_user: User = Depends(require_user)
) -> BrandingResponse:
    tenant = await get_default_tenant(db)
    settings = await _get_or_create_settings(db, tenant.id)
    settings.logo_asset_id = None
    await db.commit()
    return BrandingResponse(logo_asset_id=None, footer_year_default=settings.footer_year_default)
