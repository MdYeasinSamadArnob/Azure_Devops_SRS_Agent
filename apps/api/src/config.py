from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    # Browser-reachable host:port for MinIO — presigned URLs are signed
    # against this, not `minio_endpoint` (which is the internal Docker
    # address and unusable from outside the compose network).
    minio_public_endpoint: str | None = None

    app_secret_key: str
    pat_encryption_key: str
    cors_origins: str = "http://localhost:3000"
    azure_devops_api_version: str = "7.1"
    local_asset_fallback_dir: str | None = None
    # Advanced-deployment override only — left unset (the default), the
    # local-fallback download URL is derived from the incoming request's own
    # host (see assets.py), so it works from whatever device asked for it
    # without needing this set at all for the common case.
    api_public_base_url: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # mypy doesn't know pydantic-settings populates required fields from the
    # environment/.env at runtime, not from constructor args — this is a
    # known false positive, not a real missing-argument bug.
    return Settings()  # type: ignore[call-arg]
