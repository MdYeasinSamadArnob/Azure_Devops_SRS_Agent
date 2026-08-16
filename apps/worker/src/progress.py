"""Every pipeline stage transition goes through here: it updates the owning
job row in Postgres (durable, authoritative), inserts a job_events row (what
SSE replays from on reconnect), and publishes to Redis (low-latency push to
whoever is currently connected). SSE is a notification channel over this
durable state, never the source of truth by itself.
"""

import json
import logging
from functools import lru_cache
from typing import Any

import redis
from sqlalchemy.orm import Session
from srs_core.db.models import GenerationJob, ImportJob, JobEvent

from src.config import get_worker_settings

logger = logging.getLogger(__name__)


@lru_cache
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_worker_settings().redis_url)


def report_stage(
    session: Session,
    *,
    job_id: str,
    job_type: str,
    stage: str,
    status: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    progress_percent: int | None = None,
) -> None:
    model = ImportJob if job_type == "import" else GenerationJob
    job = session.get(model, job_id)
    if job is not None:
        job.stage = stage
        if status is not None:
            job.status = status
        if progress_percent is not None:
            job.progress_percent = progress_percent
        session.add(job)

    event = JobEvent(job_id=job_id, job_type=job_type, stage=stage, message=message, payload=payload)
    session.add(event)

    # Commits immediately, not just flushes — this is what makes every stage
    # transition (including a failure) durable on its own, regardless of
    # what happens later in the same task. A flush alone is visible only
    # within the current transaction; if the task goes on to raise, the
    # surrounding session_scope() rolls that transaction back and silently
    # erases the very failure state mark_failed just wrote, leaving the job
    # stuck at its last stage forever instead of showing as failed.
    session.commit()

    try:
        _redis_client().publish(
            f"job:{job_id}:events",
            json.dumps({"stage": stage, "message": message, "progress_percent": progress_percent}),
        )
    except redis.RedisError:
        # Live push is best-effort — job_events remains the durable record
        # that SSE replays from, so a Redis hiccup never loses progress.
        pass


def mark_failed_unless_retrying(celery_task, session: Session, *, job_id: str, job_type: str, error_message: str) -> None:
    """For tasks with `autoretry_for` configured: only marks the job failed
    on the FINAL attempt. Azure DevOps has shown real transient errors
    against this org (an identical request succeeded on manual retry
    seconds later) — marking the job failed on the first hiccup when
    Celery is about to silently retry anyway would show the user a false
    "failed" that flips back to "running", which is more confusing than
    just staying "running" through the retry.
    """
    retries_remaining = celery_task.request.retries < (celery_task.max_retries or 0)
    if retries_remaining:
        logger.info(
            "job %s hit a retryable error (attempt %d/%d), not marking failed yet: %s",
            job_id,
            celery_task.request.retries + 1,
            celery_task.max_retries,
            error_message,
        )
        return
    mark_failed(session, job_id=job_id, job_type=job_type, error_message=error_message)


def mark_failed(session: Session, *, job_id: str, job_type: str, error_message: str) -> None:
    model = ImportJob if job_type == "import" else GenerationJob
    job = session.get(model, job_id)
    if job is not None:
        job.status = "failed"
        job.error_message = error_message
        session.add(job)
    report_stage(session, job_id=job_id, job_type=job_type, stage="failed", status="failed", message=error_message)
