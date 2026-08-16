"""Connectivity smoke-test task — proves the worker can reach Postgres, Redis,
and MinIO. Not part of the IMPORT/GENERATE pipelines; used by Increment 1
verification only.
"""

import sqlalchemy as sa
from srs_core.storage.minio_client import MinioClient, MinioSettings

from src.celery_app import celery_app
from src.config import get_worker_settings


@celery_app.task(name="src.tasks.health_tasks.ping")
def ping() -> dict[str, str]:
    settings = get_worker_settings()
    checks: dict[str, str] = {}

    try:
        engine = sa.create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"

    try:
        client = MinioClient(
            MinioSettings(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        )
        client.ensure_buckets()
        checks["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["minio"] = f"error: {exc}"

    return checks
