import logging

import redis.asyncio as aioredis
from botocore.exceptions import EndpointConnectionError
from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.session import get_db_session
from src.minio.deps import get_minio_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness only — does not touch dependencies."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness probe must not raise
        logger.warning("readiness check failed: postgres: %s", exc)
        checks["postgres"] = "error"

    settings = get_settings()
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness check failed: redis: %s", exc)
        checks["redis"] = "error"

    try:
        get_minio_client().ensure_buckets()
        checks["minio"] = "ok"
    except EndpointConnectionError as exc:
        logger.warning("readiness check failed: minio: %s", exc)
        checks["minio"] = "error"
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness check failed: minio: %s", exc)
        checks["minio"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
