# Architecture

C4-style Context and Container diagrams for SRS Agent, plus a precise answer to "what does the LLM actually do" — it's used in exactly one place, for one narrow purpose, and is never required for the app to function.

## System Context

Who/what interacts with SRS Agent, and why.

```mermaid
flowchart TB
    user["👤 User<br/>Project manager / BA<br/>curating an SRS"]

    subgraph boundary [" "]
        system["SRS Agent<br/><br/>Imports an Azure DevOps backlog,<br/>lets a user curate exactly what<br/>belongs in the doc, seals an<br/>immutable snapshot, and generates<br/>a branded DOCX/PDF from it"]
    end

    azure["☁️ Azure DevOps<br/><br/>Source of the work-item<br/>hierarchy, attachments,<br/>and embedded diagrams"]

    llm["🤖 LLM Provider<br/><br/>Ollama / OpenAI / Azure OpenAI /<br/>anything litellm supports"]

    user -->|"Imports, curates, seals,<br/>generates, downloads —<br/>via the browser"| system
    system -->|"Fetches the Epic → Feature →<br/>Story → Task/Bug hierarchy +<br/>attachments, using the user's PAT"| azure
    system -.->|"Optional: asks for a short,<br/>grounded Introduction paragraph.<br/>Generation works fully without this."| llm
```

## Containers

The deployable units inside the system boundary, and how they talk to each other. Matches `docker-compose.yml` one-to-one.

```mermaid
flowchart TB
    user["👤 User<br/>Browser"]
    azure["☁️ Azure DevOps"]
    llm["🤖 LLM Provider<br/>via litellm"]

    subgraph system ["SRS Agent"]
        web["<b>web</b><br/>Next.js (App Router)<br/><br/>Atomic-design UI —<br/>import form, selection tree,<br/>generation status, downloads"]

        api["<b>api</b><br/>FastAPI<br/><br/>REST + SSE, session-cookie auth,<br/>Alembic migrations, presigned<br/>download URLs"]

        worker_default["<b>worker-default</b><br/>Celery — default queue<br/><br/>run_import, run_seal:<br/>fetch hierarchy, download<br/>attachments, seal snapshot"]

        worker_document["<b>worker-document</b><br/>Celery — document queue<br/><br/>normalize_content, run_llm_rules,<br/>render_docx, verify_document"]

        worker_conversion["<b>worker-conversion</b><br/>Celery — conversion queue<br/>(isolated: 1 worker, own queue)<br/><br/>convert_pdf via headless<br/>LibreOffice"]

        postgres[("<b>postgres</b><br/><br/>projects, snapshots,<br/>work items, users, jobs")]
        redis[("<b>redis</b><br/><br/>Celery broker +<br/>result backend")]
        minio[("<b>minio</b><br/><br/>S3-compatible —<br/>source attachments +<br/>generated documents")]
    end

    user -->|HTTPS| web
    web -->|"REST (JSON) + SSE<br/>(live job progress)"| api

    api -->|reads / writes| postgres
    api -->|enqueues tasks| redis
    api -->|"presigned URLs,<br/>branding logo upload,<br/>server-side asset copy<br/>for reselect-and-regenerate"| minio

    redis -.->|dequeues| worker_default
    redis -.->|dequeues| worker_document
    redis -.->|dequeues| worker_conversion

    worker_default -->|writes import/seal state| postgres
    worker_default -->|"fetches hierarchy +<br/>downloads attachments<br/>(PAT auth)"| azure
    worker_default -->|uploads source assets| minio

    worker_document -->|reads snapshot data| postgres
    worker_document -->|downloads source images| minio
    worker_document -->|uploads rendered DOCX| minio
    worker_document -.->|"AI Introduction<br/>paragraph (optional)"| llm

    worker_conversion -->|"downloads DOCX,<br/>uploads PDF"| minio
    worker_conversion -->|writes conversion state| postgres
```

A few things this diagram intentionally shows that are easy to miss reading the code cold:

- **Three separate Celery workers, not one** — `convert_pdf` is pinned to its own single-concurrency `conversion` queue specifically so a hung or heavy LibreOffice process can never starve the `import`/`render` pipelines (see `apps/worker/src/celery_app.py`'s `task_routes`).
- **"Reselect & regenerate" never touches Azure DevOps or Celery at all** — forking a new snapshot from an already-sealed one (`POST /snapshots/{id}/branch`) runs synchronously inside the `api` container itself: it copies rows in Postgres and does a server-side MinIO-to-MinIO object copy. No worker, no Azure API call, no re-download — that's the whole point of the feature.
- **The dotted lines to the LLM Provider are deliberately optional** — see below.

## What the LLM actually does

Exactly one thing, in exactly one place: `apps/worker/src/tasks/generate_pipeline.py::run_llm_rules`, running on `worker-document`.

- **Input**: the titles + a short snippet of description (and any custom fields like Business Rules / Functional Requirements) from up to `MAX_EPICS_IN_LLM_PROMPT` Epics in the sealed selection.
- **Output**: a 2-3 paragraph Introduction section for the generated document — prose only, no markdown, explicitly instructed not to invent anything not implied by the Epics it was given.
- **Everything else in the document is `SOURCE_EXTRACTED`, verbatim, always** — titles, IDs, states, descriptions, acceptance criteria, tables, diagrams. The LLM never touches any of that; it only ever writes the one narrative paragraph, and even that is clearly attributable to being AI-generated rather than pulled from Azure DevOps.
- **It's entirely optional.** If `MODEL_NAME` isn't set, `get_default_adapter()` returns `None` and `run_llm_rules` returns immediately — the Introduction just uses a deterministic default instead. If the provider is unreachable, slow, or errors, the task catches it, logs a warning, and generation continues exactly the same way. An LLM failure has never once failed a document generation by design — see the task's own docstring for the "controlled enhancement, never a dependency" reasoning.
- **Provider-neutral** — routed through [litellm](https://github.com/BerriAI/litellm), so `MODEL_NAME`'s prefix (`ollama/...`, `gpt-4o`, `azure/...`) selects the backend; `OLLAMA_BASE_URL` only matters for the `ollama/` case.
