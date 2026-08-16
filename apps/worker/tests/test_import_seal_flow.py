"""Increment 2/3 integration test: runs run_import then run_seal against the
real Postgres/Redis/MinIO stack (already up via docker-compose), with the
Azure DevOps HTTP calls mocked — this sandbox has no real Azure DevOps
credentials to test against, so mocking is how the pipeline logic gets
verified end-to-end.
"""

import pytest
from srs_core.db.models import Asset, ImportJob, SnapshotRelation, SnapshotWorkItem, SourceSnapshot

from src.tasks import import_pipeline
from src.tasks.import_pipeline import AzureDevOpsClient


def test_run_import_persists_hierarchy(db_session, fixture_import_job, azure_mocks):
    import_job, snapshot, connection = fixture_import_job

    result = import_pipeline.run_import(str(import_job.id), str(snapshot.id), str(connection.id))

    assert result["status"] == "completed"
    assert result["roots"] == 1  # only the Epic has no parent

    db_session.expire_all()
    items = db_session.query(SnapshotWorkItem).filter(SnapshotWorkItem.snapshot_id == snapshot.id).all()
    by_azure_id = {item.azure_work_item_id: item for item in items}
    assert set(by_azure_id.keys()) == {101, 102, 103}
    assert by_azure_id[102].parent_id == by_azure_id[101].id
    assert by_azure_id[103].parent_id == by_azure_id[102].id
    assert by_azure_id[101].parent_id is None

    relations = db_session.query(SnapshotRelation).filter(SnapshotRelation.snapshot_id == snapshot.id).all()
    assert len(relations) == 2

    refreshed_job = db_session.get(ImportJob, import_job.id)
    assert refreshed_job.status == "completed"


def test_run_seal_downloads_assets_and_seals(db_session, fixture_import_job, azure_mocks):
    import_job, snapshot, connection = fixture_import_job
    import_pipeline.run_import(str(import_job.id), str(snapshot.id), str(connection.id))

    result = import_pipeline.run_seal(str(import_job.id), str(snapshot.id), str(connection.id))

    assert result["status"] == "sealed"
    assert result["assets"] == 1  # only Story Three has an attachment

    db_session.expire_all()
    refreshed_snapshot = db_session.get(SourceSnapshot, snapshot.id)
    assert refreshed_snapshot.status == "sealed"
    assert refreshed_snapshot.sealed_at is not None
    assert len(refreshed_snapshot.manifest["assets"]) == 1
    assert refreshed_snapshot.manifest["assets"][0]["sha256"]

    assets = db_session.query(Asset).filter(Asset.snapshot_id == snapshot.id).all()
    assert len(assets) == 1
    assert assets[0].download_status == "completed"
    assert assets[0].content_type == "image/png"
    assert assets[0].sha256_hash


def test_run_import_persists_failed_status_on_final_attempt(db_session, fixture_import_job, azure_mocks, monkeypatch):
    """Regression test for a real production bug: an unexpected mid-task
    exception (e.g. a genuine Azure API error) was correctly caught and
    `mark_failed` was called, but the task then re-raised the exception —
    and the surrounding session_scope() rolls the transaction back on any
    exception, silently erasing the very 'failed' status mark_failed just
    wrote. The job was left stuck at its last stage forever, looking like
    it was still running, instead of showing as failed.

    `max_retries` is forced to 0 here so this specific failure is
    immediately treated as the final attempt — retry-eligible failures are
    deliberately NOT marked failed yet (see test_progress.py), since Celery
    will actually retry those in production.
    """
    import_job, snapshot, connection = fixture_import_job
    monkeypatch.setattr(import_pipeline.run_import, "max_retries", 0)

    async def fake_get_work_items_batch_raises(self, ids, fields=None, on_omitted=None):
        raise RuntimeError("simulated Azure 404 mid-import")

    monkeypatch.setattr(AzureDevOpsClient, "get_work_items_batch", fake_get_work_items_batch_raises)

    with pytest.raises(RuntimeError, match="simulated Azure 404"):
        import_pipeline.run_import(str(import_job.id), str(snapshot.id), str(connection.id))

    db_session.expire_all()
    refreshed_job = db_session.get(ImportJob, import_job.id)
    assert refreshed_job.status == "failed"
    assert "simulated Azure 404" in refreshed_job.error_message


def test_run_import_does_not_mark_failed_while_retries_remain(db_session, fixture_import_job, azure_mocks, monkeypatch):
    """The other half of the same fix: a retry-eligible failure must leave
    the job as 'running' (Celery will retry it), not flip to 'failed' and
    then silently flip back — that's more confusing than staying 'running'
    through the retry.
    """
    import_job, snapshot, connection = fixture_import_job

    async def fake_get_work_items_batch_raises(self, ids, fields=None, on_omitted=None):
        raise RuntimeError("simulated transient error")

    monkeypatch.setattr(AzureDevOpsClient, "get_work_items_batch", fake_get_work_items_batch_raises)

    with pytest.raises(RuntimeError, match="simulated transient error"):
        import_pipeline.run_import(str(import_job.id), str(snapshot.id), str(connection.id))

    db_session.expire_all()
    refreshed_job = db_session.get(ImportJob, import_job.id)
    assert refreshed_job.status == "running"


def test_sealed_snapshot_rejects_further_writes(db_session, fixture_import_job, azure_mocks):
    """DB-level immutability trigger: once sealed, no more writes to child tables."""
    import_job, snapshot, connection = fixture_import_job
    import_pipeline.run_import(str(import_job.id), str(snapshot.id), str(connection.id))
    import_pipeline.run_seal(str(import_job.id), str(snapshot.id), str(connection.id))

    db_session.expire_all()
    rogue_item = SnapshotWorkItem(
        snapshot_id=snapshot.id,
        azure_work_item_id=999,
        work_item_type="Bug",
        title="should be rejected",
        state="New",
    )
    db_session.add(rogue_item)
    with pytest.raises(Exception, match="sealed and immutable"):
        db_session.commit()
    db_session.rollback()
