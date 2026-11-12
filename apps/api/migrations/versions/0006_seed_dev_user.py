"""seed dev@erainfotechbd.com login

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26

Seeds a second login so it exists on every fresh database this project is
composed on. Same approach as 0004's superuser: only a bcrypt digest
(computed out-of-band) is stored here, never the plaintext. Idempotent —
if the user was already inserted by hand, the existing row is left alone.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_USER_EMAIL = "dev@erainfotechbd.com"
_USER_PASSWORD_HASH = "$2b$12$IsS5oAth103LnhE5a/CfUeI18O77pEwreJ2CrywTDFIipxM5vURwe"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email, password_hash, is_superuser) "
            "SELECT gen_random_uuid(), id, :email, :password_hash, true FROM tenants WHERE slug = 'default' "
            "ON CONFLICT (email) DO NOTHING"
        ).bindparams(email=_USER_EMAIL, password_hash=_USER_PASSWORD_HASH)
    )


def downgrade() -> None:
    # Sessions reference users.id, so drop them first. Projects/jobs the user
    # created keep their rows but would block the delete via created_by_user_id,
    # so this only succeeds for a user who hasn't created anything yet.
    op.execute(
        sa.text("DELETE FROM user_sessions WHERE user_id IN (SELECT id FROM users WHERE email = :email)").bindparams(
            email=_USER_EMAIL
        )
    )
    op.execute(sa.text("DELETE FROM users WHERE email = :email").bindparams(email=_USER_EMAIL))
