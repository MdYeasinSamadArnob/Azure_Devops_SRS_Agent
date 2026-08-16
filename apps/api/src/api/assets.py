import uuid

from botocore.exceptions import ConnectionError as BotoConnectionError
from botocore.exceptions import EndpointConnectionError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import Asset
from src.database.session import get_db_session
from src.minio.deps import get_local_fallback_store, get_minio_client
from srs_core.storage.local_fallback import LocalFallbackStore
from srs_core.storage.minio_client import MinioClient

router = APIRouter(prefix="/assets", tags=["assets"])

PRESIGNED_URL_TTL_SECONDS = 600

# MinIO's S3-API host port, per docker-compose.yml's default port mapping
# (9020:9000) — only relevant when MINIO_PUBLIC_ENDPOINT isn't explicitly set.
_DEFAULT_MINIO_PUBLIC_PORT = "9020"


def _minio_public_endpoint_for(request: Request) -> str | None:
    """Explicit MINIO_PUBLIC_ENDPOINT wins (advanced deployments — a
    non-default port, a reverse proxy, MinIO on a different host entirely).
    Left unset, derive it from whatever host the browser used to reach the
    API itself — this is what makes presigned URLs work from any device
    without per-deployment config, the same approach as the frontend's
    api-base-url.ts.
    """
    configured = get_settings().minio_public_endpoint
    if configured:
        return configured
    hostname = request.url.hostname
    if not hostname:
        return None
    return f"{hostname}:{_DEFAULT_MINIO_PUBLIC_PORT}"


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
    source: str  # "minio" | "local_fallback" — surfaced for observability, not required by the frontend


def _is_minio_unreachable(exc: Exception) -> bool:
    return isinstance(exc, (EndpointConnectionError, BotoConnectionError, ConnectionError, TimeoutError))


@router.get("/{asset_id}/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    minio: MinioClient = Depends(get_minio_client),
    local_store: LocalFallbackStore | None = Depends(get_local_fallback_store),
) -> PresignedUrlResponse:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    # Phase 1 has no real multi-tenant auth to check ownership against yet —
    # Phase 5 adds the authorization check here before issuance, per the plan.

    try:
        exists_in_minio = minio.object_exists(asset.bucket, asset.object_key)
    except Exception as exc:  # noqa: BLE001
        if not _is_minio_unreachable(exc):
            raise
        exists_in_minio = None  # MinIO itself is unreachable, not just this object missing

    if exists_in_minio is True:
        url = minio.presigned_get_url(
            asset.bucket,
            asset.object_key,
            original_filename=asset.original_filename or "download",
            expires_seconds=PRESIGNED_URL_TTL_SECONDS,
            endpoint_override=_minio_public_endpoint_for(request),
        )
        return PresignedUrlResponse(url=url, expires_in_seconds=PRESIGNED_URL_TTL_SECONDS, source="minio")

    # exists_in_minio is False (confirmed missing, MinIO reachable) or None
    # (MinIO unreachable) — either way, only a local mirror copy can help.
    if local_store is not None and local_store.exists(asset.bucket, asset.object_key):
        settings = get_settings()
        # Explicit API_PUBLIC_BASE_URL wins (advanced deployments); otherwise
        # this same request's own base URL — it's already proof the API is
        # reachable at this address from wherever the caller is.
        base_url = settings.api_public_base_url or str(request.base_url).rstrip("/")
        url = f"{base_url}/assets/{asset_id}/download-local"
        return PresignedUrlResponse(url=url, expires_in_seconds=PRESIGNED_URL_TTL_SECONDS, source="local_fallback")

    if exists_in_minio is False:
        raise HTTPException(status_code=404, detail="asset object not found in storage")
    raise HTTPException(status_code=503, detail="object storage is unreachable and no local fallback copy exists")


@router.get("/{asset_id}/download-local")
async def download_local_fallback(
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    local_store: LocalFallbackStore | None = Depends(get_local_fallback_store),
) -> Response:
    """Serves the local-disk mirror directly — used only when MinIO is
    unreachable (or the object is missing there) and the requested
    presigned-url response pointed here instead.
    """
    if local_store is None:
        raise HTTPException(status_code=503, detail="no local fallback storage configured")

    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")

    try:
        data = local_store.read(asset.bucket, asset.object_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no local fallback copy for this asset") from None

    filename = asset.original_filename or "download"
    return Response(
        content=data,
        media_type=asset.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
