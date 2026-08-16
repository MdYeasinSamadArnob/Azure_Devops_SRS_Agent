"""sealed snapshot immutability trigger

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

Enforces at the DB layer what the application already enforces at the
service layer: once a source_snapshots row is 'sealed', nothing may insert
or update snapshot_work_items / snapshot_relations / assets rows pointing
at it. assets.snapshot_id is nullable (generated-document assets have no
snapshot), so the check is skipped when it's NULL.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION prevent_write_to_sealed_snapshot() RETURNS TRIGGER AS $$
DECLARE
    snap_status TEXT;
BEGIN
    IF NEW.snapshot_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT status INTO snap_status FROM source_snapshots WHERE id = NEW.snapshot_id;

    IF snap_status = 'sealed' THEN
        RAISE EXCEPTION 'snapshot % is sealed and immutable', NEW.snapshot_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_FUNCTION_SQL)
    for table in ("snapshot_work_items", "snapshot_relations", "assets"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_seal_immutable
            BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_write_to_sealed_snapshot();
            """
        )


def downgrade() -> None:
    for table in ("snapshot_work_items", "snapshot_relations", "assets"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_seal_immutable ON {table};")
    op.execute("DROP FUNCTION IF EXISTS prevent_write_to_sealed_snapshot();")
