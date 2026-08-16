"""Phase 1 ORM models — see the plan doc for full schema rationale.

Naming: `srs_projects` (not `projects`) to stay unambiguous against Azure
DevOps "projects"; `snapshot_work_items` (not `work_items`) since a work
item row is always scoped to one immutable snapshot.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from srs_core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class User(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", onupdate=datetime.utcnow)


class UserSession(Base, UUIDPrimaryKeyMixin):
    """Backs cookie-based auth — the cookie holds only this row's `id`, no
    user data. Deleting the row is the entire logout/revocation mechanism,
    which is the whole reason this is session-based rather than JWT.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrgBrandingSettings(Base, UUIDPrimaryKeyMixin):
    """One row per tenant. `logo_asset_id IS NULL` means "use the org
    template's baked-in logo" — the current, unchanged default; a row only
    needs to exist once a tenant actually overrides something.
    """

    __tablename__ = "org_branding_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, unique=True)
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True)
    footer_year_default: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", onupdate=datetime.utcnow)


class AzureConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "azure_connections"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    srs_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("srs_projects.id"), nullable=True
    )
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="pat")
    encrypted_pat: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    azure_org: Mapped[str] = mapped_column(String(255), nullable=False)
    azure_project: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (CheckConstraint("auth_type in ('pat','oauth')", name="ck_azure_connections_auth_type"),)


class SrsProject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "srs_projects"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    azure_org: Mapped[str] = mapped_column(String(255), nullable=False)
    azure_project: Mapped[str] = mapped_column(String(255), nullable=False)
    azure_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", onupdate=datetime.utcnow)


class ImportJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "import_jobs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    srs_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("srs_projects.id"), nullable=False)
    azure_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("azure_connections.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "source_snapshots"

    srs_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("srs_projects.id"), nullable=False)
    import_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_jobs.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    query_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="creating")
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Despite the underlying JSONB column, every write site assigns a plain
    # list of Azure work-item ids (see import_pipeline.py's run_seal and
    # snapshot_selection.py's branch_snapshot) — dict[str, Any] here was
    # never accurate.
    root_work_item_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()", onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("status in ('creating','validating','sealed','failed')", name="ck_source_snapshots_status"),
    )


class SnapshotWorkItem(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "snapshot_work_items"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=False
    )
    azure_work_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_item_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("snapshot_work_items.id"), nullable=True
    )
    parent_azure_work_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    area_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    iteration_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="source_extracted")
    azure_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (UniqueConstraint("snapshot_id", "azure_work_item_id", name="uq_snapshot_work_item"),)


class SnapshotRelation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "snapshot_relations"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=False
    )
    source_azure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_azure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False)


class Asset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    # Nullable: a tenant-level asset (e.g. an org branding logo, see
    # OrgBrandingSettings) isn't scoped to any one srs_project.
    srs_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("srs_projects.id"), nullable=True
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=True
    )
    generated_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_documents.id"), nullable=True
    )
    snapshot_work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("snapshot_work_items.id"), nullable=True
    )
    asset_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    azure_relation_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    download_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_assets_bucket_object_key"),
        CheckConstraint(
            "asset_kind in ('source_attachment','generated_document','snapshot_manifest','preview','template')",
            name="ck_assets_asset_kind",
        ),
        CheckConstraint(
            "download_status in ('pending','downloading','completed','failed','partial')",
            name="ck_assets_download_status",
        ),
    )


class SrsSelection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "srs_selections"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=False
    )
    snapshot_work_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("snapshot_work_items.id"), nullable=False
    )
    is_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    overridden_order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GenerationJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generation_jobs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    srs_project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("srs_projects.id"), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GeneratedDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generated_documents"

    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_jobs.id"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id"), nullable=False
    )
    # NOT globally unique: one generation event (docx + pdf together) shares
    # a single generation_id across multiple rows, one per format — only the
    # (generation_id, format) pair must be unique.
    generation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("format in ('docx','pdf','html')", name="ck_generated_documents_format"),
        UniqueConstraint("generation_id", "format", name="uq_generated_documents_generation_format"),
    )


class JobEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "job_events"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (CheckConstraint("job_type in ('import','generate','asset_retry','convert')", name="ck_job_events_job_type"),)
