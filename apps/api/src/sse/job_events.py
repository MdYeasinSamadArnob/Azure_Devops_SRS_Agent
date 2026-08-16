"""SSE is a notification channel over durable Postgres state, never the
source of truth by itself. On connect/reconnect this replays every
job_events row the client missed (using the `Last-Event-ID` header the
browser's EventSource sends automatically) before switching to live Redis
pub/sub — so a dropped connection or an API restart mid-job never loses
progress from the client's perspective.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.models import GenerationJob, ImportJob, JobEvent
from src.database.session import async_session_factory

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
KEEPALIVE_SECONDS = 15


def _format_sse(event_id: str, data: dict) -> str:
    return f"id: {event_id}\ndata: {json.dumps(data)}\n\n"


async def _get_job_status(db: AsyncSession, job_id: str) -> str | None:
    # Unrolled rather than looped over (ImportJob, GenerationJob) — iterating
    # a tuple of model classes widens db.get()'s return type to the shared
    # declarative Base, which has no .status attribute, for mypy.
    import_job = await db.get(ImportJob, job_id)
    if import_job is not None:
        return import_job.status
    generation_job = await db.get(GenerationJob, job_id)
    if generation_job is not None:
        return generation_job.status
    return None


async def stream_job_events(
    db: AsyncSession, job_id: str, last_event_id: str | None
) -> AsyncIterator[str]:
    query = select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.created_at)
    if last_event_id:
        try:
            cursor = datetime.fromisoformat(last_event_id)
            query = query.where(JobEvent.created_at > cursor)
        except ValueError:
            pass  # malformed cursor — fall back to replaying full history

    result = await db.execute(query)
    backlog = list(result.scalars().all())
    for event in backlog:
        yield _format_sse(
            event.created_at.isoformat(),
            {"stage": event.stage, "message": event.message, "progress_percent": None},
        )

    status = await _get_job_status(db, job_id)

    # Release the request-scoped connection back to the pool now — this
    # generator can stay alive for as long as a client keeps a job's
    # progress page open (potentially minutes), and holding one pooled
    # connection per open stream for that whole duration is what exhausted
    # the pool under real usage (reproduced live: QueuePool limit reached,
    # blocking unrelated requests like /import/discover, with only a
    # handful of job-progress tabs open). Every check from here on opens
    # its own short-lived session instead of reusing this one.
    await db.close()

    if status in TERMINAL_STATUSES:
        return  # job already finished — no need to hold the connection open for live updates

    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"job:{job_id}:events")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=KEEPALIVE_SECONDS)
            if message is None:
                yield ": keepalive\n\n"
                # Terminal check on every keepalive so the generator exits
                # once the job finishes even if Redis delivery was missed.
                # Fresh short-lived session — see the note above `db.close()`.
                async with async_session_factory() as session:
                    status = await _get_job_status(session, job_id)
                if status in TERMINAL_STATUSES:
                    return
                continue
            payload = json.loads(message["data"])
            yield _format_sse(datetime.utcnow().isoformat(), payload)
            if payload.get("stage") == "completed" or payload.get("stage") == "failed":
                return
    finally:
        await pubsub.unsubscribe(f"job:{job_id}:events")
        await pubsub.aclose()
        await redis_client.aclose()
