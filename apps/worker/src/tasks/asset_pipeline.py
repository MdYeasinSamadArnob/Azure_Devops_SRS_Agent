"""Attachment + embedded-image pipeline: discover Azure "AttachedFile"
relations AND <img> tags embedded directly in description/acceptance-criteria
HTML, download concurrently (bounded), MIME-sniff, hash, upload to MinIO,
record an Asset row. A failure on any one image produces a warning and a
`failed` download_status — it must never fail the whole IMPORT job for one
bad image.

Concurrency model: HTTP downloads run concurrently via asyncio (this is an
I/O-bound workload — many small network round-trips, not CPU work), bounded
by a semaphore so we don't overwhelm Azure DevOps or exhaust local sockets.
The MinIO upload itself is a blocking boto3 call, so it's offloaded to a
thread via `asyncio.to_thread` — otherwise one upload would stall every
other in-flight download on the same event loop.
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass

import httpx
from srs_core.enums import BUCKET_SOURCE_ASSETS
from srs_core.parsing.html_images import EmbeddedImageRef
from srs_core.security.file_signature import sniff_content_type
from srs_core.storage.minio_client import MinioClient, MinioSettings, source_asset_key

from src.config import get_worker_settings
from src.storage_helpers import upload_with_fallback

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/bmp",
    "image/webp",
    "application/pdf",
}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
DEFAULT_DOWNLOAD_CONCURRENCY = 8


def _get_minio_client() -> MinioClient:
    settings = get_worker_settings()
    return MinioClient(
        MinioSettings(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    )


def extract_attachment_relations(raw_item: dict) -> list[dict]:
    return [rel for rel in raw_item.get("relations", []) or [] if rel.get("rel") == "AttachedFile"]


@dataclass
class DownloadJob:
    snapshot_work_item_id: uuid.UUID
    source_kind: str  # "attachment" | "embedded_azure" | "embedded_data_uri" | "embedded_external"
    source_url: str
    original_filename: str
    azure_relation_type: str
    # Only set for embedded_data_uri — bytes already available, no download needed.
    decoded_bytes: bytes | None = None


def build_download_jobs(
    snapshot_work_item_id: uuid.UUID,
    *,
    raw_item: dict,
    embedded_images: list[EmbeddedImageRef],
) -> list[DownloadJob]:
    jobs: list[DownloadJob] = []

    for relation in extract_attachment_relations(raw_item):
        jobs.append(
            DownloadJob(
                snapshot_work_item_id=snapshot_work_item_id,
                source_kind="attachment",
                source_url=relation.get("url", ""),
                original_filename=(relation.get("attributes", {}) or {}).get("name") or "attachment",
                azure_relation_type=relation.get("rel") or "AttachedFile",
            )
        )

    for idx, ref in enumerate(embedded_images):
        if ref.kind == "data_uri":
            jobs.append(
                DownloadJob(
                    snapshot_work_item_id=snapshot_work_item_id,
                    source_kind="embedded_data_uri",
                    source_url=ref.src[:200],  # data URIs can be huge; keep source_url bounded
                    original_filename=f"embedded-{idx}",
                    azure_relation_type="EmbeddedImage",
                    decoded_bytes=ref.decoded_bytes,
                )
            )
        else:
            jobs.append(
                DownloadJob(
                    snapshot_work_item_id=snapshot_work_item_id,
                    source_kind=f"embedded_{ref.kind}",
                    source_url=ref.src,
                    original_filename=f"embedded-{idx}",
                    azure_relation_type="EmbeddedImage",
                )
            )

    return jobs


async def _process_bytes(
    *,
    body: bytes,
    header_content_type: str,
    original_filename: str,
    tenant_id: uuid.UUID,
    srs_project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> tuple[str, str, str, int]:
    """Returns (object_key, content_type, sha256_hash, byte_size), raises on
    any validation/upload failure — caller decides how to record that.
    """
    # Azure often serves attachments as generic application/octet-stream
    # regardless of the real file type — trust the actual file signature
    # (then filename extension) over that header.
    content_type = sniff_content_type(body, original_filename, header_content_type)

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"content-type '{content_type}' not in MIME allowlist")
    if len(body) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"attachment exceeds {MAX_ATTACHMENT_BYTES} byte limit")

    sha256_hash = hashlib.sha256(body).hexdigest()
    asset_id = uuid.uuid4()
    object_key = source_asset_key(str(tenant_id), str(srs_project_id), str(snapshot_id), str(asset_id), original_filename)

    # Blocking boto3 call — offloaded so it can't stall other in-flight
    # downloads sharing this event loop.
    await asyncio.to_thread(upload_with_fallback, _get_minio_client(), BUCKET_SOURCE_ASSETS, object_key, body, content_type)

    return object_key, content_type, sha256_hash, len(body)


async def run_download_job(
    job: DownloadJob,
    *,
    http_client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    tenant_id: uuid.UUID,
    srs_project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> dict:
    """Returns a plain dict describing the outcome — the caller (holding the
    single DB session) turns this into an Asset row. Never raises: a bad
    image must not take down the whole import.
    """
    result = {
        "snapshot_work_item_id": job.snapshot_work_item_id,
        "source_url": job.source_url,
        "original_filename": job.original_filename,
        "azure_relation_type": job.azure_relation_type,
        "status": "failed",
        "object_key": None,
        "content_type": None,
        "sha256_hash": None,
        "byte_size": 0,
    }

    async with semaphore:
        try:
            if job.decoded_bytes is not None:
                body = job.decoded_bytes
                header_content_type = ""
            else:
                response = await http_client.get(job.source_url, timeout=30.0)
                response.raise_for_status()
                header_content_type = response.headers.get("content-type", "").split(";")[0].strip()
                body = response.content

            object_key, content_type, sha256_hash, byte_size = await _process_bytes(
                body=body,
                header_content_type=header_content_type,
                original_filename=job.original_filename,
                tenant_id=tenant_id,
                srs_project_id=srs_project_id,
                snapshot_id=snapshot_id,
            )
            result.update(
                status="completed",
                object_key=object_key,
                content_type=content_type,
                sha256_hash=sha256_hash,
                byte_size=byte_size,
            )
        except Exception as exc:  # noqa: BLE001 — one bad image must not fail the whole import
            logger.warning("image download failed for %s (%s): %s", job.source_url, job.source_kind, exc)

    return result
