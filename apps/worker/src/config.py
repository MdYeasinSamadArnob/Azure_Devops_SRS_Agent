import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    database_url_sync: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    pat_encryption_key: str
    local_asset_fallback_dir: str | None


def get_worker_settings() -> WorkerSettings:
    # Celery tasks run synchronously — use the psycopg2 driver, not asyncpg,
    # even though the API process uses the async driver for the same DB.
    async_url = os.environ["DATABASE_URL"]
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return WorkerSettings(
        database_url_sync=sync_url,
        redis_url=os.environ["REDIS_URL"],
        celery_broker_url=os.environ["CELERY_BROKER_URL"],
        celery_result_backend=os.environ["CELERY_RESULT_BACKEND"],
        minio_endpoint=os.environ["MINIO_ENDPOINT"],
        minio_access_key=os.environ["MINIO_ACCESS_KEY"],
        minio_secret_key=os.environ["MINIO_SECRET_KEY"],
        minio_secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
        pat_encryption_key=os.environ["PAT_ENCRYPTION_KEY"],
        local_asset_fallback_dir=os.environ.get("LOCAL_ASSET_FALLBACK_DIR") or None,
    )
