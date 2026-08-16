"""Regression tests for src.progress — the durable-commit fix and the
retry-aware failure marking, both found via a real production incident:
an unexpected mid-task error left a job stuck at its last stage forever
instead of showing as failed, because mark_failed's writes were rolled
back by the very `raise` meant to propagate the error.
"""

from unittest.mock import MagicMock

from srs_core.db.models import ImportJob

from src.progress import mark_failed_unless_retrying


def _fake_celery_task(retries: int, max_retries: int) -> MagicMock:
    task = MagicMock()
    task.request.retries = retries
    task.max_retries = max_retries
    return task


def test_does_not_mark_failed_when_retries_remain(db_session, default_tenant, fixture_import_job):
    import_job, _snapshot, _connection = fixture_import_job
    task = _fake_celery_task(retries=0, max_retries=3)

    mark_failed_unless_retrying(
        task, db_session, job_id=str(import_job.id), job_type="import", error_message="transient error"
    )
    # mark_failed/report_stage commit internally now — that's the actual fix
    # under test: the write must survive regardless of what happens next.

    db_session.expire_all()
    refreshed = db_session.get(ImportJob, import_job.id)
    assert refreshed.status != "failed"


def test_marks_failed_on_final_attempt(db_session, default_tenant, fixture_import_job):
    import_job, _snapshot, _connection = fixture_import_job
    task = _fake_celery_task(retries=3, max_retries=3)

    mark_failed_unless_retrying(
        task, db_session, job_id=str(import_job.id), job_type="import", error_message="still failing"
    )

    db_session.expire_all()
    refreshed = db_session.get(ImportJob, import_job.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "still failing"
