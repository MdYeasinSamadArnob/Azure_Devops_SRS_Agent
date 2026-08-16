"""users, sessions, org branding settings, and per-row creator tracking

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14

Adds real login: a `users` table (scoped to the existing single `tenants`
row via `tenant_id`, so this is additive, not a rework), a `sessions` table
backing httpOnly session-cookie auth (chosen over JWT so logout/revocation
is just deleting a row), and `org_branding_settings` (one row per tenant,
letting the document logo/footer-year default be overridden from the UI
instead of only the org template's baked-in values).

`created_by_user_id` is added to `azure_connections`, `srs_projects`,
`source_snapshots`, and `generation_jobs` (which previously had NO creator
tracking at all) — additive alongside the existing free-text
`created_by_email` columns, not replacing them, so nothing existing breaks.

Seeds the one requested superuser account. The password hash below is a
bcrypt digest computed once out-of-band — the plaintext password is never
present in this file, in application logs, or anywhere else in the system.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_SUPERUSER_EMAIL = "era@erainfotechbd.com"
_SUPERUSER_PASSWORD_HASH = "$2b$12$pdBUqV/cVeDMFb8A9MDvIOs4/oSGotLzABYKvu7bnwyyt6/TtrFmu"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    op.create_table(
        "org_branding_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("logo_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("footer_year_default", sa.String(16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    for table in ("azure_connections", "srs_projects", "source_snapshots", "generation_jobs"):
        op.add_column(
            table, sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True)
        )

    op.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email, password_hash, is_superuser) "
            "SELECT gen_random_uuid(), id, :email, :password_hash, true FROM tenants WHERE slug = 'default'"
        ).bindparams(email=_SUPERUSER_EMAIL, password_hash=_SUPERUSER_PASSWORD_HASH)
    )

    # Every project/connection/snapshot/generation created before login
    # existed was, in practice, created by whoever was operating the
    # system — which is this same seeded superuser. Backfilling avoids
    # that pre-auth work silently disappearing from "my projects" the
    # first time someone actually logs in.
    for table in ("azure_connections", "srs_projects", "source_snapshots", "generation_jobs"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET created_by_user_id = "  # noqa: S608 — table is one of 4 hardcoded literals above
                "(SELECT id FROM users WHERE email = :email) "
                "WHERE created_by_user_id IS NULL"
            ).bindparams(email=_SUPERUSER_EMAIL)
        )


def downgrade() -> None:
    for table in ("azure_connections", "srs_projects", "source_snapshots", "generation_jobs"):
        op.drop_column(table, "created_by_user_id")
    op.drop_table("org_branding_settings")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("users")
