"""S3-compatible object storage wrapper around MinIO.

Used by both the API (to mint presigned URLs) and the worker (to upload
source assets / generated documents). Never expose the underlying boto3
client's credentials to a caller outside this module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from srs_core.enums import ALL_BUCKETS

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(original_filename: str) -> str:
    """Normalize an untrusted filename for use inside an object key.

    Never trust an Azure-supplied filename directly in a MinIO key: it may
    contain path separators, null bytes, or unicode tricks. The original
    filename is preserved separately in Postgres for display purposes.
    """
    normalized = unicodedata.normalize("NFKD", original_filename)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.replace("/", "_").replace("\\", "_")
    normalized = _SANITIZE_RE.sub("_", normalized).strip("._")
    return normalized or "unnamed"


def source_asset_key(tenant_id: str, project_id: str, snapshot_id: str, asset_id: str, original_filename: str) -> str:
    return f"{tenant_id}/{project_id}/{snapshot_id}/{asset_id}/{sanitize_filename(original_filename)}"


def template_key(tenant_id: str, template_id: str, version: int) -> str:
    return f"{tenant_id}/{template_id}/{version}/template.docx"


def generated_document_key(tenant_id: str, srs_project_id: str, generation_id: str, filename: str) -> str:
    return f"{tenant_id}/{srs_project_id}/{generation_id}/{sanitize_filename(filename)}"


def build_document_filename(title: str, generated_at: datetime, extension: str) -> str:
    """The human-facing download filename for a generated document —
    independent of the MinIO object key, which stays a fixed
    `document.<ext>` basename under its own unique-namespaced path.
    """
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    return f"{sanitize_filename(title)}_{timestamp}.{extension}"


@dataclass(frozen=True)
class MinioSettings:
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool = False
    # The host:port a BROWSER can reach MinIO at — e.g. "localhost:9020" in
    # dev — as opposed to `endpoint`, which is the internal Docker-network
    # address used for every server-to-server call (upload/download/head).
    # A presigned URL signed with the internal address is unusable outside
    # the Docker network, so URL generation needs its own client bound to
    # this instead. Defaults to `endpoint` when not set (single-host setups).
    public_endpoint: str | None = None


class MinioClient:
    """Thin wrapper around boto3's S3 client, scoped to the app's known buckets."""

    def __init__(self, settings: MinioSettings) -> None:
        self._scheme = "https" if settings.secure else "http"
        self._access_key = settings.access_key
        self._secret_key = settings.secret_key
        self._client = boto3.client(
            "s3",
            endpoint_url=f"{self._scheme}://{settings.endpoint}",
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            config=BotoConfig(signature_version="s3v4"),
        )

        default_public_endpoint = settings.public_endpoint or settings.endpoint
        self._signing_client = (
            self._client
            if default_public_endpoint == settings.endpoint
            else self._build_signing_client(default_public_endpoint)
        )

    def _build_signing_client(self, endpoint: str) -> Any:
        # Presigned URL generation is pure local signature computation — this
        # client never makes a network call, it only needs the right host
        # baked into the signed URL. Cheap to construct on demand per-request
        # (see presigned_get_url's endpoint_override) since nothing here
        # touches the network.
        return boto3.client(
            "s3",
            endpoint_url=f"{self._scheme}://{endpoint}",
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            config=BotoConfig(signature_version="s3v4"),
        )

    def ensure_buckets(self) -> None:
        """Idempotently create every bucket the app depends on.

        Safety net alongside the declarative `minio-init` compose service —
        useful if the API is ever run outside compose (e.g. `uvicorn` directly).
        """
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        for bucket in ALL_BUCKETS:
            if bucket in existing:
                continue
            try:
                self._client.create_bucket(Bucket=bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise

    def upload_bytes(self, bucket: str, object_key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=bucket, Key=object_key, Body=data, ContentType=content_type)

    def download_bytes(self, bucket: str, object_key: str) -> bytes:
        return self._client.get_object(Bucket=bucket, Key=object_key)["Body"].read()

    def copy_object(self, *, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        """Server-side copy — the bytes never leave MinIO. Used when a snapshot
        is forked (see reselect-and-regenerate): the new snapshot's assets get
        their own object_key (required by the assets table's unique
        (bucket, object_key) constraint) without re-fetching anything from
        Azure DevOps or round-tripping the bytes through the API process.
        """
        self._client.copy_object(Bucket=dst_bucket, Key=dst_key, CopySource={"Bucket": src_bucket, "Key": src_key})

    def object_exists(self, bucket: str, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=bucket, Key=object_key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise

    def presigned_get_url(
        self,
        bucket: str,
        object_key: str,
        *,
        original_filename: str,
        expires_seconds: int = 600,
        endpoint_override: str | None = None,
    ) -> str:
        """Mint a short-lived download URL. Caller MUST authorize the request first.

        `endpoint_override` lets a caller sign against a host it derived
        itself (e.g. from the incoming request, so the URL is reachable from
        whatever device actually asked for it) instead of the one fixed
        `MINIO_PUBLIC_ENDPOINT` this client was constructed with.
        """
        if not (60 <= expires_seconds <= 900):
            raise ValueError("presigned URL TTL must be between 60s and 15 minutes")
        signing_client = self._build_signing_client(endpoint_override) if endpoint_override else self._signing_client
        return signing_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ResponseContentDisposition": f'attachment; filename="{sanitize_filename(original_filename)}"',
            },
            ExpiresIn=expires_seconds,
        )
