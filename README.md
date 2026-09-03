# SRS Agent

Turn an Azure DevOps backlog into a professional Software Requirements Specification document — import the work-item hierarchy, curate exactly what belongs in the doc, seal an immutable snapshot, and generate AI-enhanced DOCX/PDF output from your org's own branded template.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it does

1. **Import** — paste an Azure DevOps backlog or work-item URL; SRS Agent walks the Epic → Feature → Story → Task/Bug hierarchy (including embedded diagrams and attachments) using your Personal Access Token.
2. **Curate** — pick exactly which work items belong in the document from a tree view, with bulk select-by-type shortcuts.
3. **Seal** — locks the curated selection into an immutable snapshot. Nothing about a sealed snapshot can change — regenerating always starts from an explicit, auditable selection.
4. **Generate** — renders a DOCX (and optionally PDF) straight from your organization's own `.docx` template, preserving its styles, headers/footers, and branding, with optional AI enhancement of narrative sections.
5. **Reselect & regenerate** — come back later, change the selection, and regenerate — without ever re-hitting Azure DevOps for data or images already fetched.

Every project keeps full version history: every past generation stays downloadable, never overwritten by a later run.

## Architecture

A single monolithic monorepo — no microservices, no premature abstraction:

```
apps/
  web/            Next.js (App Router) frontend — atomic design (atoms → molecules → organisms → templates → pages)
  api/             FastAPI — thin routers, session-cookie auth, Alembic migrations
  worker/          Celery workers — import, generate, asset, and PDF-conversion pipelines
packages/
  srs_core/        Shared Python: Azure DevOps client, MinIO wrapper, crypto, rendering, parsing
  contracts/        Reserved for generated API types once the OpenAPI schema stabilizes
infra/
  docker/           Postgres/MinIO init scripts used by docker-compose
templates/           .docx template(s) used as the base for generated documents (one is proprietary and supplied separately — see "Template setup" below)
```

Data flow: **Azure DevOps → import pipeline → Postgres (draft snapshot) → user curation → sealed snapshot → generate pipeline → DOCX/PDF in MinIO**. Source attachments and generated documents are both content-addressed objects in MinIO; a "reselect & regenerate" forks a new snapshot and copies assets forward via a server-side MinIO copy — it never re-downloads from Azure DevOps.

See **[docs/architecture.md](docs/architecture.md)** for C4 Context/Container diagrams and exactly what the LLM does (and doesn't do) in the pipeline.

## Tech stack

- **Frontend**: Next.js, React, TypeScript, Tailwind
- **Backend**: FastAPI (async), SQLAlchemy 2.0, Alembic, Celery
- **Storage**: Postgres, Redis (Celery broker), MinIO (S3-compatible object storage)
- **Documents**: python-docx (direct document construction from a real org template), LibreOffice (headless, for PDF conversion)
- **AI**: provider-neutral via [litellm](https://github.com/BerriAI/litellm) — works with Ollama, OpenAI, Azure OpenAI, or any litellm-supported provider
- **Monorepo tooling**: [Turborepo](https://turbo.build/) orchestrating both the npm workspace (frontend) and the Poetry-managed Python services

## Quickstart

**Requirements**: Docker, Docker Compose, Node.js 20+.

```bash
git clone <this-repo>
cd srs_agent
cp .env.example .env      # edit values — see comments in the file
docker compose up -d
```

### Template setup (required for "Generate Formatted SRS")

The newer, more structured document pipeline ("Generate Formatted SRS" in the UI) renders onto `templates/ERA_SRS_Template_V2.1.docx` — ERA InfoTech's own branded SRS template. It's proprietary and **not included in this open-source repository**; the file is handed out separately (ask a maintainer). Place it at exactly:

```
templates/ERA_SRS_Template_V2.1.docx
```

before running `docker compose build worker-document` (or `docker compose up -d --build`) — the worker image copies whatever's in `templates/` at build time, so the file must be in place first. Without it, every other feature works normally; only "Generate Formatted SRS" jobs fail (cleanly, with a clear error) until the template is added and the image is rebuilt.

The original "Generate Document" pipeline's template (`templates/main_template_SRS-Customer-BankAsiaSmartApp-V0.5.8.docx`) already ships in the repo, so no extra setup is needed for it.

- Web app: http://localhost:3010
- API: http://localhost:8010
- MinIO console: http://localhost:9021 (see `.env` for credentials)

The database migrations run automatically on API startup. A superuser account is seeded by migration `0004` — see that migration's docstring for how to change the seeded credentials before your first deploy.

### Start / stop / logs

```bash
docker compose up -d              # start everything (also picks up code changes after a rebuild)
docker compose down                # stop everything
```

```bash
docker compose logs -f                    # follow logs for every service
docker compose logs -f web api             # follow just the frontend + API
docker compose logs -f worker-default worker-document worker-conversion  # follow the Celery workers
```

Every service also runs the same way if you're working on it directly — e.g. after editing backend or frontend code, rebuild just that one service and watch its logs:

```bash
docker compose build api && docker compose up -d --no-deps api && docker compose logs -f api
```

### Production mode

`docker compose up` always runs the frontend's `next dev` server — there's no dev/prod distinction for the API or workers (`uvicorn` already runs without `--reload`, and the Celery workers run the same either way), so only `web` needs a separate mode. Run everything with the frontend's optimized production build instead:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # start in production mode
docker compose -f docker-compose.yml -f docker-compose.prod.yml down             # stop
```

This builds `apps/web`'s `prod` Dockerfile target — `next build`'s minimal standalone output (`node server.js`), not the dev server — on the same ports as above. Switch back to dev mode with a plain `docker compose up -d --build` (`docker compose down` stops either mode the same way, since it's the same set of container names either way).

### Monorepo commands (Turborepo)

```bash
npm install        # once, at the repo root
npm run lint        # lints every workspace (eslint for web, ruff for the Python services)
npm run test         # runs every workspace's test suite
npm run typecheck    # tsc for web, mypy for apps/api
npm run build         # next build for web
```

Turbo orchestrates the task graph across the npm workspace (`apps/web`) and the Poetry-managed Python services (`apps/api`, `apps/worker`, `packages/srs_core`) — the Python workspaces' scripts shell out to `docker compose run`, since the test suite needs real Postgres/Redis/MinIO, not mocks.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, coding conventions, and how to submit a pull request. Please also read our [Code of Conduct](CODE_OF_CONDUCT.md).

Found a security issue? Please see [SECURITY.md](SECURITY.md) rather than opening a public issue.

## License

[MIT](LICENSE)
