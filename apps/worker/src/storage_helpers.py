"""Every object the worker uploads to MinIO is also mirrored to local disk
(best-effort) so a download can still succeed if MinIO becomes unreachable
later. MinIO stays the primary store — a failure mirroring to disk is
logged and swallowed, never allowed to fail the pipeline; a failure
uploading to MinIO itself still fails normally.
"""

import logging

from srs_core.storage.local_fallback import LocalFallbackStore
from srs_core.storage.minio_client import MinioClient

from src.config import get_worker_settings

logger = logging.getLogger(__name__)


def get_local_fallback_store() -> LocalFallbackStore | None:
    settings = get_worker_settings()
    if not settings.local_asset_fallback_dir:
        return None
    return LocalFallbackStore(settings.local_asset_fallback_dir)


def upload_with_fallback(minio_client: MinioClient, bucket: str, object_key: str, data: bytes, content_type: str) -> None:
    minio_client.upload_bytes(bucket, object_key, data, content_type)

    store = get_local_fallback_store()
    if store is None:
        return
    try:
        store.write(bucket, object_key, data)
    except Exception:  # noqa: BLE001 — the mirror is a resilience extra, never a hard dependency
        logger.warning("local fallback mirror write failed for %s/%s", bucket, object_key, exc_info=True)
