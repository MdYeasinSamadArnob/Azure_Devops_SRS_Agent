from celery import Celery

from src.config import get_worker_settings

_settings = get_worker_settings()

celery_app = Celery(
    "srs_agent_worker",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
)

celery_app.conf.update(
    task_routes={
        "src.tasks.import_pipeline.*": {"queue": "default"},
        "src.tasks.generate_pipeline.*": {"queue": "document"},
        "src.tasks.generate_pipeline.convert_pdf": {"queue": "conversion"},
        "src.tasks.convert.*": {"queue": "conversion"},
    },
    task_default_queue="default",
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
)

from src import tasks  # noqa: E402, F401 — import triggers task registration
