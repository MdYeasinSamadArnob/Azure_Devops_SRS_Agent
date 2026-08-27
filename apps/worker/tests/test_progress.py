"""Regression tests for src.progress — the durable-commit fix and the
retry-aware failure marking, both found via a real production incident:
an unexpected mid-task error left a job stuck at its last stage forever
instead of showing as failed, because mark_failed's writes were rolled
back by the very `raise` meant to propagate the error.
"""

from unittest.mock import MagicMock

from srs_core.db.models import ImportJob
from srs_core.progress_stages import GENERATE_STAGE_ORDER, IMPORT_STAGE_ORDER, progress_percent_for_stage

from src.progress import mark_failed_unless_retrying, report_stage


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


# -- Progress percentage ---------------------------------------------------
#
# Regression coverage for a real reported bug: the progress percentage
# shown on the frontend never moved past its initial value. Root cause:
# report_stage's progress_percent parameter was never passed by any of its
# 17 call sites across both pipelines, so the DB column never got written.


def test_progress_percent_for_stage_is_evenly_spaced_by_position():
    assert progress_percent_for_stage("generate", "queued") == 0
    assert progress_percent_for_stage("generate", "completed") == 100
    # Position 3 of 7 (0-indexed) in GENERATE_STAGE_ORDER -> 3/6 = 50%.
    assert GENERATE_STAGE_ORDER[3] == "rendering_docx"
    assert progress_percent_for_stage("generate", "rendering_docx") == 50

    assert progress_percent_for_stage("import", "queued") == 0
    assert progress_percent_for_stage("import", "completed") == 100
    assert IMPORT_STAGE_ORDER[4] == "fetching_work_items"
    assert progress_percent_for_stage("import", "fetching_work_items") == 57


def test_progress_percent_for_stage_returns_none_for_failed_and_unknown_stages():
    assert progress_percent_for_stage("generate", "failed") is None
    assert progress_percent_for_stage("import", "failed") is None
    assert progress_percent_for_stage("generate", "some_future_stage") is None


def test_report_stage_writes_the_computed_percent_when_none_given(db_session, default_tenant, fixture_import_job):
    import_job, _snapshot, _connection = fixture_import_job

    report_stage(db_session, job_id=str(import_job.id), job_type="import", stage="fetching_work_items")

    db_session.expire_all()
    refreshed = db_session.get(ImportJob, import_job.id)
    assert refreshed.progress_percent == progress_percent_for_stage("import", "fetching_work_items")


def test_report_stage_leaves_progress_percent_untouched_on_failed_stage(db_session, default_tenant, fixture_import_job):
    import_job, _snapshot, _connection = fixture_import_job

    report_stage(db_session, job_id=str(import_job.id), job_type="import", stage="downloading_assets")
    db_session.expire_all()
    percent_before_failure = db_session.get(ImportJob, import_job.id).progress_percent

    report_stage(db_session, job_id=str(import_job.id), job_type="import", stage="failed", status="failed")

    db_session.expire_all()
    refreshed = db_session.get(ImportJob, import_job.id)
    assert refreshed.status == "failed"
    assert refreshed.progress_percent == percent_before_failure  # frozen at the point of failure, not reset
