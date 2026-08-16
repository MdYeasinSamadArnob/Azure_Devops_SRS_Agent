"""fix generation_id uniqueness scope

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

Bug fix: generation_id was uniquely constrained per-row, but one GENERATE
run producing both docx and pdf needs two generated_documents rows sharing
the same generation_id (that's what "same generation" means). Replace the
column-level unique constraint with a composite (generation_id, format)
constraint instead.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("generated_documents_generation_id_key", "generated_documents", type_="unique")
    op.create_unique_constraint(
        "uq_generated_documents_generation_format", "generated_documents", ["generation_id", "format"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_generated_documents_generation_format", "generated_documents", type_="unique")
    op.create_unique_constraint("generated_documents_generation_id_key", "generated_documents", ["generation_id"])
