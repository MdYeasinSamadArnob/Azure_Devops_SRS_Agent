FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

# libreoffice-writer + fonts are only exercised by the `conversion` queue,
# but all worker services share this one image for simplicity.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    fonts-dejavu \
    fonts-liberation \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==1.8.3

WORKDIR /app

COPY packages/srs_core /app/packages/srs_core
COPY apps/worker/pyproject.toml apps/worker/poetry.lock* /app/apps/worker/

WORKDIR /app/apps/worker
RUN poetry install --no-root --no-ansi

COPY apps/worker /app/apps/worker
COPY templates /app/templates

CMD ["celery", "-A", "src.celery_app", "worker", "--loglevel=INFO", "-Q", "default"]
