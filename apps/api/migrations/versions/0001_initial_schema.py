"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-11

"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "srs_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("azure_org", sa.String(255), nullable=False),
        sa.Column("azure_project", sa.String(255), nullable=False),
        sa.Column("azure_base_url", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by_email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "azure_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("srs_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("srs_projects.id"), nullable=True),
        sa.Column("auth_type", sa.String(16), nullable=False, server_default="pat"),
        sa.Column("encrypted_pat", sa.Text, nullable=True),
        sa.Column("oauth_access_token_encrypted", sa.Text, nullable=True),
        sa.Column("oauth_refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("azure_org", sa.String(255), nullable=False),
        sa.Column("azure_project", sa.String(255), nullable=False),
        sa.Column("created_by_email", sa.String(320), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("auth_type in ('pat','oauth')", name="ck_azure_connections_auth_type"),
    )

    op.create_table(
        "import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("srs_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("srs_projects.id"), nullable=False),
        sa.Column(
            "azure_connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("azure_connections.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="queued"),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("warnings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "source_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("srs_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("srs_projects.id"), nullable=False),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("query_params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="creating"),
        sa.Column("manifest", postgresql.JSONB, nullable=True),
        sa.Column("root_work_item_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status in ('creating','validating','sealed','failed')", name="ck_source_snapshots_status"),
    )

    op.create_table(
        "snapshot_work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False
        ),
        sa.Column("azure_work_item_id", sa.Integer, nullable=False),
        sa.Column("work_item_type", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("snapshot_work_items.id"), nullable=True),
        sa.Column("parent_azure_work_item_id", sa.Integer, nullable=True),
        sa.Column("area_path", sa.Text, nullable=True),
        sa.Column("iteration_path", sa.Text, nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_selected", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("raw_fields", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("description_html", sa.Text, nullable=True),
        sa.Column("acceptance_criteria", postgresql.JSONB, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("priority", sa.String(32), nullable=True),
        sa.Column("provenance", sa.String(32), nullable=False, server_default="source_extracted"),
        sa.Column("azure_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_id", "azure_work_item_id", name="uq_snapshot_work_item"),
    )
    op.create_index("ix_snapshot_work_items_parent_id", "snapshot_work_items", ["parent_id"])

    op.create_table(
        "snapshot_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False
        ),
        sa.Column("source_azure_id", sa.Integer, nullable=False),
        sa.Column("target_azure_id", sa.Integer, nullable=False),
        sa.Column("relation_type", sa.String(128), nullable=False),
    )

    op.create_table(
        "generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("srs_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("srs_projects.id"), nullable=False),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="queued"),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("params", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # assets <-> generated_documents is a circular FK relationship:
    # create assets first with generated_document_id as a plain (unconstrained) column,
    # create generated_documents referencing assets.id, then attach the deferred FK.
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("srs_project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("srs_projects.id"), nullable=False),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=True
        ),
        sa.Column("generated_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "snapshot_work_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshot_work_items.id"),
            nullable=True,
        ),
        sa.Column("asset_kind", sa.String(32), nullable=False),
        sa.Column("bucket", sa.String(64), nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("original_filename", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("azure_relation_type", sa.String(128), nullable=True),
        sa.Column("download_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("bucket", "object_key", name="uq_assets_bucket_object_key"),
        sa.CheckConstraint(
            "asset_kind in ('source_attachment','generated_document','snapshot_manifest','preview','template')",
            name="ck_assets_asset_kind",
        ),
        sa.CheckConstraint(
            "download_status in ('pending','downloading','completed','failed','partial')",
            name="ck_assets_download_status",
        ),
    )

    op.create_table(
        "generated_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "generation_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_jobs.id"), nullable=False
        ),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("format in ('docx','pdf','html')", name="ck_generated_documents_format"),
    )

    op.create_foreign_key(
        "fk_assets_generated_document_id",
        "assets",
        "generated_documents",
        ["generated_document_id"],
        ["id"],
    )

    op.create_table(
        "srs_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_snapshots.id"), nullable=False
        ),
        sa.Column(
            "snapshot_work_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("snapshot_work_items.id"),
            nullable=False,
        ),
        sa.Column("is_included", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("overridden_order_index", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("job_type in ('import','generate','asset_retry','convert')", name="ck_job_events_job_type"),
    )
    op.create_index("ix_job_events_job_id_created_at", "job_events", ["job_id", "created_at"])

    op.execute(
        "INSERT INTO tenants (id, slug, name) VALUES (gen_random_uuid(), 'default', 'Default Tenant')"
    )


def downgrade() -> None:
    op.drop_table("job_events")
    op.drop_table("srs_selections")
    op.drop_constraint("fk_assets_generated_document_id", "assets", type_="foreignkey")
    op.drop_table("generated_documents")
    op.drop_table("assets")
    op.drop_table("generation_jobs")
    op.drop_table("snapshot_relations")
    op.drop_index("ix_snapshot_work_items_parent_id", table_name="snapshot_work_items")
    op.drop_table("snapshot_work_items")
    op.drop_table("source_snapshots")
    op.drop_table("import_jobs")
    op.drop_table("azure_connections")
    op.drop_table("srs_projects")
    op.drop_table("tenants")
