"""Regression tests for a real reported bug: the selection tree and
generated document order didn't match Azure Boards' own backlog order —
items came out sorted by internal Azure work item ID (fetch/insertion
order) instead of the org's actual manually-arranged backlog priority.

Verified live against the real org: ascending `Microsoft.VSTS.Common.
StackRank` exactly matched the "Order" column Azure Boards shows in its
backlog view.
"""

from srs_core.azure.client import WorkItemNode
from srs_core.db.models import SnapshotWorkItem

from src.tasks import import_pipeline


def test_order_index_for_uses_stack_rank_when_present():
    assert import_pipeline._order_index_for({"Microsoft.VSTS.Common.StackRank": 1234.0}) == 1234


def test_order_index_for_falls_back_to_backlog_priority_field():
    # Some Agile-process templates use this field name instead of StackRank.
    assert import_pipeline._order_index_for({"Microsoft.VSTS.Common.BacklogPriority": 42.0}) == 42


def test_order_index_for_defaults_to_max_when_no_rank_field_present():
    # Sorts after every ranked sibling rather than crashing or defaulting to 0
    # (which would incorrectly sort an unranked item FIRST).
    assert import_pipeline._order_index_for({}) == import_pipeline._ORDER_INDEX_MAX


def test_order_index_for_clamps_pathological_values():
    # order_index is a 32-bit column — clamp rather than risk an overflow error.
    huge = 9_999_999_999.0
    assert import_pipeline._order_index_for({"Microsoft.VSTS.Common.StackRank": huge}) == import_pipeline._ORDER_INDEX_MAX


def test_persist_tree_orders_siblings_by_stack_rank_not_azure_id(db_session, fixture_import_job):
    _import_job, snapshot, _connection = fixture_import_job

    # Deliberately out of azure_id order but with meaningful StackRank
    # values — item 103 has the highest id but the LOWEST rank, so it must
    # sort first; 101 has the lowest id but the highest rank, so it must
    # sort last.
    lowest_rank = WorkItemNode(
        azure_id=103,
        work_item_type="Feature",
        title="Highest priority (lowest rank)",
        state="New",
        fields={"Microsoft.VSTS.Common.StackRank": 1000.0},
        parent_azure_id=200,
    )
    middle_rank = WorkItemNode(
        azure_id=102,
        work_item_type="Feature",
        title="Middle priority",
        state="New",
        fields={"Microsoft.VSTS.Common.StackRank": 2000.0},
        parent_azure_id=200,
    )
    highest_rank = WorkItemNode(
        azure_id=101,
        work_item_type="Feature",
        title="Lowest priority (highest rank)",
        state="New",
        fields={"Microsoft.VSTS.Common.StackRank": 3000.0},
        parent_azure_id=200,
    )
    epic = WorkItemNode(
        azure_id=200,
        work_item_type="Epic",
        title="Epic",
        state="New",
        fields={},
        children=[middle_rank, highest_rank, lowest_rank],  # deliberately shuffled
    )

    import_pipeline._persist_tree(db_session, snapshot.id, [epic], org="test-org", project="proj")
    db_session.commit()

    rows = (
        db_session.query(SnapshotWorkItem)
        .filter(SnapshotWorkItem.snapshot_id == snapshot.id, SnapshotWorkItem.work_item_type == "Feature")
        .order_by(SnapshotWorkItem.order_index, SnapshotWorkItem.azure_work_item_id)
        .all()
    )
    assert [r.azure_work_item_id for r in rows] == [103, 102, 101]
