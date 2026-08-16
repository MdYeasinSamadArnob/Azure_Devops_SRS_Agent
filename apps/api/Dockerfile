FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir poetry==1.8.3

WORKDIR /app

COPY packages/srs_core /app/packages/srs_core
COPY apps/api/pyproject.toml apps/api/poetry.lock* /app/apps/api/

WORKDIR /app/apps/api
RUN poetry install --no-root --no-ansi

COPY apps/api /app/apps/api

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
