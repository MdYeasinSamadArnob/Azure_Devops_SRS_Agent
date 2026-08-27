"""Canonical, ordered pipeline stage lists for import/generate jobs, and the
percentage each stage maps to — shared between apps/api and apps/worker
(two separate deployables that only share code through this package) so
that write-time computation (worker, via report_stage) and read-time
computation (api, replaying JobEvent history over SSE) can never drift
apart: both call the exact same function on the exact same stage string.

Evenly spaced by position in the list, not by estimated duration — there's
no per-stage timing data to weight by, and even spacing stays correct on
its own whenever a stage is added or removed here, with no other code
needing to change.

Must match apps/web/src/lib/types.ts's `ImportStage`/`GenerateStage` unions
and the stage strings actually passed to `report_stage(..., stage=...)`
throughout apps/worker/src/tasks/generate_pipeline.py and import_pipeline.py.
"""

from __future__ import annotations

GENERATE_STAGE_ORDER = [
    "queued",
    "normalizing_content",
    "running_llm_rules",
    "rendering_docx",
    "converting_pdf",
    "verifying_document",
    "completed",
]

IMPORT_STAGE_ORDER = [
    "queued",
    "authenticating",
    "discovering_fields",
    "fetching_hierarchy",
    "fetching_work_items",
    "downloading_assets",
    "creating_snapshot",
    "completed",
]


def progress_percent_for_stage(job_type: str, stage: str) -> int | None:
    """None for a stage not in the canonical list (e.g. "failed") — the
    caller should leave progress_percent untouched in that case, so the UI
    freezes at whatever percent the job had reached right before it failed
    instead of jumping to some arbitrary number.
    """
    order = IMPORT_STAGE_ORDER if job_type == "import" else GENERATE_STAGE_ORDER
    if stage not in order:
        return None
    return round(order.index(stage) / (len(order) - 1) * 100)
