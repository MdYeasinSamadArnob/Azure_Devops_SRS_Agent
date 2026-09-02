"""Thin Celery client used only to enqueue tasks by name — the API process
never imports worker task code, it just needs the same broker.
"""

from functools import lru_cache

from celery import Celery, chain, signature

from src.config import get_settings


@lru_cache
def get_celery_client() -> Celery:
    settings = get_settings()
    return Celery(broker=settings.celery_broker_url, backend=settings.celery_result_backend)


def enqueue_import_pipeline(*, import_job_id: str, snapshot_id: str, connection_id: str) -> str:
    result = get_celery_client().send_task(
        "src.tasks.import_pipeline.run_import",
        kwargs={"import_job_id": import_job_id, "snapshot_id": snapshot_id, "connection_id": connection_id},
        queue="default",
    )
    return result.id


def enqueue_seal_pipeline(*, import_job_id: str, snapshot_id: str, connection_id: str) -> str:
    result = get_celery_client().send_task(
        "src.tasks.import_pipeline.run_seal",
        kwargs={"import_job_id": import_job_id, "snapshot_id": snapshot_id, "connection_id": connection_id},
        queue="default",
    )
    return result.id


def enqueue_generate_pipeline(
    *,
    generation_job_id: str,
    snapshot_id: str,
    formats: list[str],
    document_metadata: dict[str, str] | None = None,
    template_version: str = "legacy",
) -> str:
    """Builds the GENERATE chain by task name (the API never imports worker
    task code) with each stage's queue set explicitly — convert_pdf is the
    only stage on the isolated `conversion` queue, so a hung/heavy
    LibreOffice process can never starve normalization or DOCX rendering.

    `template_version`: "legacy" (default) for the original org-template
    pipeline ("Generate Document"), "v2" for the new ERA_SRS_Template_V2.1
    pipeline ("Generate Formatted SRS") — see generate_pipeline.py's
    render_docx and backlog task-15.
    """
    app = get_celery_client()
    workflow = chain(
        signature(
            "src.tasks.generate_pipeline.normalize_content",
            args=(generation_job_id, snapshot_id, formats, document_metadata or {}, template_version),
            app=app,
            queue="document",
        ),
        signature("src.tasks.generate_pipeline.run_llm_rules", app=app, queue="document"),
        signature("src.tasks.generate_pipeline.render_docx", app=app, queue="document"),
        signature("src.tasks.generate_pipeline.convert_pdf", app=app, queue="conversion"),
        signature("src.tasks.generate_pipeline.verify_document", app=app, queue="document"),
    )
    result = workflow.apply_async()
    return result.id
