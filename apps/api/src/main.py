import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.assets import router as assets_router
from src.api.auth import router as auth_router
from src.api.azure_connections import router as azure_connections_router
from src.api.azure_import import router as azure_import_router
from src.api.branding import router as branding_router
from src.api.generation import router as generation_router
from src.api.health import router as health_router
from src.api.jobs import router as jobs_router
from src.api.projects import router as projects_router
from src.api.snapshot_selection import router as snapshot_selection_router
from src.api.snapshots import router as snapshots_router
from src.auth.sessions import require_user
from src.config import get_settings
from src.minio.deps import get_minio_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Safety net alongside the declarative `minio-init` compose service.
    try:
        get_minio_client().ensure_buckets()
    except Exception:  # noqa: BLE001
        logger.exception("failed to ensure MinIO buckets on startup — minio-init should have already created them")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SRS Agent API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Every router except /health and /auth itself requires a valid session —
    # added centrally here rather than per-router so there's exactly one
    # place that decides what's behind login.
    protected = [Depends(require_user)]
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(azure_connections_router, dependencies=protected)
    app.include_router(azure_import_router, dependencies=protected)
    app.include_router(snapshots_router, dependencies=protected)
    app.include_router(snapshot_selection_router, dependencies=protected)
    app.include_router(generation_router, dependencies=protected)
    app.include_router(assets_router, dependencies=protected)
    app.include_router(jobs_router, dependencies=protected)
    app.include_router(projects_router, dependencies=protected)
    app.include_router(branding_router, dependencies=protected)

    return app


app = create_app()
