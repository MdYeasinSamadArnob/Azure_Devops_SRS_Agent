"""Regression tests for a real production bug: a work item deleted (or made
inaccessible to the importing PAT) after another item's Parent/Child relation
already pointed at it makes Azure's workitemsbatch endpoint 404 the ENTIRE
batch by default — deterministically, on every retry, not a transient blip.
Reproduced live against this org: item 109446 was unreadable
("TF401232: Work item does not exist, or you do not have permissions to read
it.") but still referenced as a Task under a Story, so every import of that
backlog failed permanently at the batch containing it.

The fix is requesting `errorPolicy: "Omit"`, which makes Azure return `null`
in that id's slot instead of failing the batch.
"""

import json

import httpx
import pytest
from srs_core.azure.client import AzureDevOpsClient


def _work_item(azure_id: int, *, children: list[int] | None = None) -> dict:
    relations = []
    for child_id in children or []:
        relations.append(
            {
                "rel": "System.LinkTypes.Hierarchy-Forward",
                "url": f"https://dev.azure.com/org/proj/_apis/wit/workItems/{child_id}",
            }
        )
    return {
        "id": azure_id,
        "fields": {
            "System.WorkItemType": "Task",
            "System.Title": f"Item {azure_id}",
            "System.State": "New",
        },
        "relations": relations,
    }


@pytest.mark.asyncio
async def test_get_work_items_batch_requests_omit_error_policy_and_skips_null_slots():
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured_bodies.append(body)
        # Simulate Azure's real behavior: id 2 is unreadable, returned as null
        # in its positional slot, the rest come back normally.
        value = [_work_item(1), None, _work_item(3)]
        return httpx.Response(200, json={"count": len(value), "value": value})

    client = AzureDevOpsClient(
        "org", "proj", "fake-pat", transport=httpx.MockTransport(handler)
    )
    try:
        omitted = []
        items = await client.get_work_items_batch([1, 2, 3], on_omitted=omitted.append)
    finally:
        await client.aclose()

    assert captured_bodies[0]["errorPolicy"] == "Omit"
    assert [item["id"] for item in items] == [1, 3]
    assert omitted == [2]


@pytest.mark.asyncio
async def test_fetch_hierarchy_from_roots_warns_and_continues_past_an_inaccessible_child():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        ids = body["ids"]
        if ids == [1]:
            value = [_work_item(1, children=[2, 3])]
        elif set(ids) == {2, 3}:
            # id 2 is the deleted/inaccessible one referenced by item 1's relation.
            value = [None if i == 2 else _work_item(i) for i in ids]
        else:
            value = []
        return httpx.Response(200, json={"count": len(value), "value": value})

    client = AzureDevOpsClient(
        "org", "proj", "fake-pat", transport=httpx.MockTransport(handler)
    )
    try:
        result = await client.fetch_hierarchy_from_roots([1])
    finally:
        await client.aclose()

    assert [node.azure_id for node in result.roots] == [1]
    assert [child.azure_id for child in result.roots[0].children] == [3]
    assert any("109446" not in w and "2" in w and "deleted or inaccessible" in w for w in result.warnings)
