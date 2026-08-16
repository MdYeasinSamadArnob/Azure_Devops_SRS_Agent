"""assets.srs_project_id nullable (tenant-level assets)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14

A tenant-level asset — the org branding logo added in 0004's
`org_branding_settings` — isn't scoped to any one `srs_project`, unlike
every other asset kind on this table (source attachments, generated
documents, ...). `snapshot_id`/`generated_document_id`/
`snapshot_work_item_id` were already nullable for the same reason;
`srs_project_id` was the one holdout still NOT NULL.
"""

from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("assets", "srs_project_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.alter_column("assets", "srs_project_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
