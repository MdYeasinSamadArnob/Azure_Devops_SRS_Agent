from functools import lru_cache

from srs_core.storage.local_fallback import LocalFallbackStore
from srs_core.storage.minio_client import MinioClient, MinioSettings

from src.config import get_settings


@lru_cache
def get_minio_client() -> MinioClient:
    settings = get_settings()
    return MinioClient(
        MinioSettings(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            public_endpoint=settings.minio_public_endpoint,
        )
    )


@lru_cache
def get_local_fallback_store() -> LocalFallbackStore | None:
    settings = get_settings()
    if not settings.local_asset_fallback_dir:
        return None
    return LocalFallbackStore(settings.local_asset_fallback_dir)
