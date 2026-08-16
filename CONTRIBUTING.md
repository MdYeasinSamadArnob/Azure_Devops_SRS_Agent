# Contributing to SRS Agent

Thanks for considering a contribution. This document covers how to get a working dev environment, how the codebase is organized, and what we look for in a pull request.

## Getting set up

1. **Requirements**: Docker, Docker Compose, Node.js 20+.
2. Clone the repo and copy the env template:
   ```bash
   cp .env.example .env
   ```
   Fill in real values where the template says `change_me_dev_only` — these are dev-only defaults, not usable secrets. `AZURE_DEVOPS_*` credentials are entered per-connection in the UI, not via `.env`.
3. Bring up the whole stack:
   ```bash
   docker compose up -d
   ```
   This starts Postgres, Redis, MinIO, the API, three Celery workers (default/document/conversion queues), and the Next.js dev server. Alembic migrations run automatically when the API container starts.
4. Install root dependencies for Turborepo:
   ```bash
   npm install
   ```

## Project structure

This is a monorepo managed by [Turborepo](https://turbo.build/). See the README's Architecture section for the full layout. A few conventions worth knowing before you dive in:

- **Frontend (`apps/web`) follows atomic design** — strict downward-only imports: `atoms` → `molecules` → `organisms` → `templates` → `app/**/page.tsx`. An atom must not import anything from `src/`; a template may compose organisms/molecules but a page's route file (`page.tsx`) should stay a thin binding (usually just resolving Next.js route params and rendering one template).
- **Backend (`apps/api`, `apps/worker`, `packages/srs_core`) follows YAGNI** — flat, one-router-per-resource FastAPI layout, one Celery task file per pipeline stage, no repository-pattern abstraction over SQLAlchemy, no DI framework beyond FastAPI's own `Depends`. Don't introduce a new architectural layer (use-cases, ports/adapters, etc.) unless the specific problem you're solving actually needs it — open an issue to discuss first if you think it does.
- **Sealed snapshots are immutable** — enforced by a Postgres trigger (`prevent_write_to_sealed_snapshot`, see migration `0002`), not just application logic. Any feature that needs to "change" a sealed snapshot's contents should fork a new snapshot (see `apps/api/src/api/snapshot_selection.py` for the pattern), never try to write around the trigger.
- **Never re-fetch from Azure DevOps when the data is already stored.** Source attachments live in MinIO once downloaded; forking a snapshot copies them server-side (`MinioClient.copy_object`) rather than re-downloading.

## Making changes

- **Rebuild before you test.** The `api`/`worker`/`web` Docker images are built from Dockerfiles with no source volume mount — editing a file on your host does **not** automatically apply inside a running container. After changing backend or frontend code, run:
  ```bash
  docker compose build <service>
  docker compose up -d --no-deps <service>
  ```
  before relying on `docker compose run`/`logs` output to reflect your change.
- **Run the checks that apply to what you touched:**
  ```bash
  npm run lint        # eslint (web) + ruff (api, worker, srs_core)
  npm run typecheck    # tsc (web) + mypy (api)
  npm run test          # pytest (worker's suite covers srs_core too — apps/api has no test suite yet, contributions welcome)
  ```
  Or scope to one workspace: `npm run lint --workspace=apps/web`, `npm run test --workspace=@srs-agent/worker`, etc.
- **Database schema changes** go through Alembic — add a new migration under `apps/api/migrations/versions/`, chained after the current head. Never hand-edit an already-applied migration.
- **Don't add abstraction, tests-for-the-sake-of-it, or speculative configuration** for scenarios the codebase doesn't need yet. Keep changes scoped to the problem at hand.

## Commit / PR conventions

- Keep pull requests focused — one logical change per PR is easier to review than a bundle of unrelated fixes.
- Write commit messages that explain **why**, not just what changed — the diff already shows what changed.
- If your change touches the document-generation pipeline (`apps/worker/src/tasks/docx_builder.py`, `packages/srs_core/srs_core/rendering/`), please describe how you verified it — ideally by generating a real document and confirming the output, since these code paths manipulate raw OOXML and are easy to break silently.
- Update `README.md`/`CONTRIBUTING.md` in the same PR if you change a documented workflow (env vars, commands, folder layout).

## Reporting bugs / requesting features

Open a GitHub issue. Please include:
- What you expected to happen vs. what actually happened
- Steps to reproduce (or the smallest repro you can manage)
- Relevant logs (`docker compose logs <service>`) — redact anything sensitive (PATs, org names, tokens) before pasting

## Security issues

Please do **not** open a public issue for a security vulnerability — see [SECURITY.md](SECURITY.md).
