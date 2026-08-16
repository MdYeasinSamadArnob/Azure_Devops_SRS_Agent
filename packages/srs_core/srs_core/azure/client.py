"""Azure DevOps REST/WIQL client with pagination, retry/backoff, and
recursive hierarchy resolution (depth-limited + cycle-detected).

This belongs in Phase 1, not later — even a moderate backlog can trigger
throttling or malformed relation graphs.

Hierarchy discovery is BFS from an explicit set of root IDs (resolved via
the Team Backlog API when a team/backlog level is known), never a blanket
project-wide WIQL scan — a project can have many thousands of work items
across dozens of teams, and only the team/backlog actually requested should
ever be fetched.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

# Azure's documented hard limit for a single workitemsbatch call.
MAX_BATCH_SIZE = 200
# The PRACTICAL chunk size we actually request at: work items with large
# custom HTML fields (data dictionaries, embedded diagrams-as-base64, ...)
# can make a 200-item response multiple megabytes and take well over a
# minute for Azure to generate — a real request against this org's backlog
# reproduced a response still transferring after 60s+ at that batch size.
# Smaller chunks fetched CONCURRENTLY keep any one response fast while
# still being no slower overall.
WORK_ITEMS_BATCH_SIZE = 50
WORK_ITEMS_BATCH_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_DEPTH = 12


class AzureDevOpsAuthError(Exception):
    """Raised when the PAT is invalid or lacks access — fail fast, not deep in the pipeline."""


class AzureDevOpsApiError(Exception):
    pass


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


def _id_from_relation_url(url: str) -> int | None:
    tail = url.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None


@dataclass
class WorkItemNode:
    azure_id: int
    work_item_type: str
    title: str
    state: str
    fields: dict[str, Any]
    parent_azure_id: int | None = None
    children: list["WorkItemNode"] = field(default_factory=list)


@dataclass
class HierarchyResult:
    roots: list[WorkItemNode]
    unlinked_ids: list[int]
    warnings: list[str]


class AzureDevOpsClient:
    def __init__(
        self,
        org: str,
        project: str,
        pat: str,
        api_version: str = "7.1",
        *,
        max_concurrency: int = 4,
        request_timeout_seconds: float = 30.0,
        max_depth: int = DEFAULT_MAX_DEPTH,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._org = org
        self._project = project
        self._api_version = api_version
        self._max_depth = max_depth
        # No fixed /_apis suffix here — team-scoped endpoints (backlogs) live
        # under /{team}/_apis/..., project-scoped ones under /_apis/... directly.
        self._client = httpx.AsyncClient(
            base_url=f"https://dev.azure.com/{org}/{project}",
            auth=("", pat),
            timeout=request_timeout_seconds,
            transport=transport,
        )
        self._semaphore_limit = max_concurrency

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _request(
        self, method: str, path: str, *, request_timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        params = kwargs.pop("params", {}) or {}
        params.setdefault("api-version", self._api_version)
        request_kwargs = dict(kwargs)
        if request_timeout is not None:
            request_kwargs["timeout"] = request_timeout
        response = await self._client.request(method, path, params=params, **request_kwargs)
        if response.status_code == 401:
            raise AzureDevOpsAuthError("PAT rejected — check token validity and org/project access")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            logger.warning("Azure DevOps rate limited, Retry-After=%s", retry_after)
        response.raise_for_status()
        return response

    async def validate_access(self) -> None:
        """Fail fast with a clear error if the PAT can't reach this org/project."""
        await self._request("GET", "/_apis/wit/workitemtypes")

    async def run_wiql(self, wiql_query: str) -> list[int]:
        response = await self._request("POST", "/_apis/wit/wiql", json={"query": wiql_query})
        payload = response.json()
        return [item["id"] for item in payload.get("workItems", [])]

    async def get_work_items_batch(
        self, ids: list[int], fields: list[str] | None = None, *, on_omitted: Any = None
    ) -> list[dict[str, Any]]:
        """Fetch work item details in chunks, fetched CONCURRENTLY (bounded
        by max_concurrency) — this is an I/O-bound workload, and one chunk
        with unusually large field content must not serialize behind (or
        block) the others.

        Uses `errorPolicy: "Omit"` deliberately: a real org backlog can have
        a Parent/Child relation pointing at a work item that was later
        deleted, or one the PAT's identity lost access to (observed live:
        Azure raises "TF401232: Work item does not exist, or you do not have
        permissions to read it." for such an id). Without `errorPolicy`,
        Azure's default is to fail the ENTIRE batch with a 404 if even one of
        up to 50 requested ids is unreadable — deterministically, on every
        retry, not a transient blip. With `Omit`, Azure instead returns the
        array with a `null` in that id's slot and 200s the rest of the batch.
        `on_omitted`, if given, is called with each omitted id so the caller
        can surface it as an import warning instead of the item silently
        vanishing from the tree.
        """
        semaphore = asyncio.Semaphore(self._semaphore_limit)

        async def fetch_chunk(chunk: list[int]) -> list[dict[str, Any]]:
            body: dict[str, Any] = {"ids": chunk, "$expand": "relations", "errorPolicy": "Omit"}
            if fields:
                body["fields"] = fields
            async with semaphore:
                response = await self._request(
                    "POST",
                    "/_apis/wit/workitemsbatch",
                    json=body,
                    request_timeout=WORK_ITEMS_BATCH_TIMEOUT_SECONDS,
                )
            raw_values = response.json().get("value", [])
            results = []
            for requested_id, item in zip(chunk, raw_values):
                if item is None:
                    logger.warning("work item %s omitted from batch response (deleted or inaccessible)", requested_id)
                    if on_omitted is not None:
                        on_omitted(requested_id)
                    continue
                results.append(item)
            return results

        chunks = [ids[start : start + WORK_ITEMS_BATCH_SIZE] for start in range(0, len(ids), WORK_ITEMS_BATCH_SIZE)]
        chunk_results = await asyncio.gather(*(fetch_chunk(chunk) for chunk in chunks))
        return [item for chunk_result in chunk_results for item in chunk_result]

    async def list_team_backlogs(self, team: str) -> list[dict[str, Any]]:
        """Returns each backlog level for a team, e.g. Epics/Features/Stories/Tasks
        (names vary by process template). Each entry's `id` is what
        `get_backlog_root_ids` needs.
        """
        response = await self._request("GET", f"/{team}/_apis/work/backlogs")
        return response.json().get("value", [])

    async def resolve_backlog_id(self, team: str, backlog_level_name: str) -> str:
        """Maps a human-readable backlog level name (from a URL, e.g. "Epics")
        to its backlog id (e.g. "Microsoft.EpicCategory"), case-insensitively.
        """
        backlogs = await self.list_team_backlogs(team)
        for backlog in backlogs:
            if backlog.get("name", "").lower() == backlog_level_name.lower():
                return backlog["id"]
        available = ", ".join(b.get("name", "?") for b in backlogs)
        raise ValueError(f"backlog level '{backlog_level_name}' not found for team '{team}' — available: {available}")

    async def get_backlog_root_ids(self, team: str, backlog_id: str) -> list[int]:
        """The work items AT this backlog level for this team — e.g. every Epic
        in the team's area path. This is the correctly-scoped starting point
        for hierarchy traversal, unlike a project-wide WIQL scan.
        """
        response = await self._request("GET", f"/{team}/_apis/work/backlogs/{backlog_id}/workItems")
        return [entry["target"]["id"] for entry in response.json().get("workItems", []) if entry.get("target")]

    async def fetch_hierarchy_from_roots(self, root_ids: list[int]) -> HierarchyResult:
        """Breadth-first traversal starting from an explicit, correctly-scoped
        root set: fetch the roots, follow their Hierarchy-Forward relations to
        find children, fetch those, repeat — bounded by max_depth and
        cycle-detected via the visited set. Never pre-fetches more than the
        actual reachable subtree, so (unlike a project-wide scan) there is no
        such thing as an "unreachable" item here by construction.
        """
        warnings: list[str] = []
        nodes: dict[int, WorkItemNode] = {}
        parent_of: dict[int, int] = {}
        visited: set[int] = set()

        frontier = list(dict.fromkeys(root_ids))  # de-duplicate while preserving order
        depth = 0
        while frontier:
            if depth > self._max_depth:
                warnings.append(f"hierarchy traversal exceeds max depth ({self._max_depth}); truncated")
                break

            to_fetch = [wid for wid in frontier if wid not in visited]
            if not to_fetch:
                break
            visited.update(to_fetch)

            raw_items = await self.get_work_items_batch(
                to_fetch,
                on_omitted=lambda wid: warnings.append(
                    f"work item {wid} was referenced by a relation but is deleted or inaccessible with this PAT; skipped"
                ),
            )
            next_frontier: list[int] = []

            for raw in raw_items:
                azure_id = raw["id"]
                fields = raw.get("fields", {})
                nodes[azure_id] = WorkItemNode(
                    azure_id=azure_id,
                    work_item_type=fields.get("System.WorkItemType", "Unknown"),
                    title=fields.get("System.Title", ""),
                    state=fields.get("System.State", ""),
                    fields=fields,
                )

                for relation in raw.get("relations", []) or []:
                    if relation.get("rel") != "System.LinkTypes.Hierarchy-Forward":
                        continue
                    child_id = _id_from_relation_url(relation.get("url", ""))
                    if child_id is None:
                        continue
                    if child_id in visited:
                        warnings.append(f"cycle detected involving work item {child_id}; traversal stopped")
                        continue
                    parent_of[child_id] = azure_id
                    if child_id not in next_frontier:
                        next_frontier.append(child_id)

            frontier = next_frontier
            depth += 1

        for child_id, parent_id in parent_of.items():
            child = nodes.get(child_id)
            parent = nodes.get(parent_id)
            if child is None or parent is None:
                continue  # parent hit max_depth before this child was fetched
            child.parent_azure_id = parent_id
            parent.children.append(child)

        roots = [nodes[rid] for rid in dict.fromkeys(root_ids) if rid in nodes]
        return HierarchyResult(roots=roots, unlinked_ids=[], warnings=warnings)
