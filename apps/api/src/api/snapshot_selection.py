"""Reselect-and-regenerate: fork a *new*, independent snapshot from an
already-sealed one with a different work-item selection, without ever
calling Azure DevOps again.

Why a fork instead of editing the sealed snapshot in place: sealed
snapshots are immutable by design (`prevent_write_to_sealed_snapshot`, a DB
trigger) and `seal_snapshot` in `azure_import.py` already refuses to reseal
anything not in `status == 'creating'`. The trigger only restricts writes
scoped to an *already-sealed* snapshot_id — a brand new snapshot_id is
unrestricted, so "copy the tree + assets into a fresh snapshot" is the
correct shape here, not a special-cased mutation path.

Every `SnapshotWorkItem` from the parent snapshot was already fetched at
import time regardless of what was selected at seal time (`is_selected` is
just a per-row flag) — so the full hierarchy is always available to
re-select from. Assets are the only thing that were selection-scoped at
download time (`_download_attachments_for_selection` only fetches for
`is_selected=True` rows), so a fork copies *every* asset from its parent
forward (not just the newly-selected ones) — this makes "no Azure re-fetch"
durable across repeated forks, not just a one-shot exception.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from srs_core.storage.minio_client import MinioClient, source_asset_key

from src.api.azure_import import DiscoveryTreeResponse, _build_tree
from src.auth.sessions import require_user
from src.database.models import Asset, ImportJob, SnapshotRelation, SnapshotWorkItem, SourceSnapshot, SrsProject, User
from src.database.session import get_db_session
from src.minio.deps import get_minio_client

router = APIRouter(prefix="/snapshots", tags=["snapshot-selection"])


async def _load_owned_snapshot(db: AsyncSession, snapshot_id: uuid.UUID, current_user: User) -> SourceSnapshot:
    snapshot = await db.get(SourceSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="snapshot not found")
    project = await db.get(SrsProject, snapshot.srs_project_id)
    # 404, not 403 — don't confirm another user's snapshot even exists.
    if project is None or project.created_by_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="snapshot not found")
    return snapshot


@router.get("/{snapshot_id}/tree", response_model=DiscoveryTreeResponse)
async def get_snapshot_tree(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_user),
) -> DiscoveryTreeResponse:
    snapshot = await _load_owned_snapshot(db, snapshot_id, current_user)
    result = await db.execute(
        select(SnapshotWorkItem)
        .where(SnapshotWorkItem.snapshot_id == snapshot.id)
        .order_by(SnapshotWorkItem.order_index, SnapshotWorkItem.azure_work_item_id)
    )
    items = list(result.scalars().all())
    return DiscoveryTreeResponse(roots=_build_tree(items), unlinked_count=0, snapshot_id=snapshot.id)


class BranchRequest(BaseModel):
    selected_azure_ids: list[int]


class BranchResponse(BaseModel):
    snapshot_id: uuid.UUID


@router.post("/{snapshot_id}/branch", response_model=BranchResponse)
async def branch_snapshot(
    snapshot_id: uuid.UUID,
    body: BranchRequest,
    db: AsyncSession = Depends(get_db_session),
    minio: MinioClient = Depends(get_minio_client),
    current_user: User = Depends(require_user),
) -> BranchResponse:
    parent = await _load_owned_snapshot(db, snapshot_id, current_user)
    if parent.status != "sealed":
        raise HTTPException(status_code=409, detail=f"snapshot is '{parent.status}', expected 'sealed'")

    project = await db.get(SrsProject, parent.srs_project_id)
    parent_job = await db.get(ImportJob, parent.import_job_id)
    if project is None or parent_job is None:
        # Both are FKs off an already-loaded, owned snapshot — only reachable
        # if the data is already inconsistent, not from anything the caller controls.
        raise HTTPException(status_code=500, detail="snapshot references missing project or import job")

    # Synthetic job: exists only so `source_snapshots.import_job_id`'s NOT
    # NULL FK is satisfied and the fork's lineage is auditable — no worker
    # task ever runs against it.
    fork_job = ImportJob(
        tenant_id=project.tenant_id,
        srs_project_id=project.id,
        azure_connection_id=parent_job.azure_connection_id,
        status="completed",
        stage="completed",
        params={"cloned_from_snapshot_id": str(parent.id)},
    )
    db.add(fork_job)
    await db.flush()

    child = SourceSnapshot(
        srs_project_id=project.id,
        import_job_id=fork_job.id,
        source_url=parent.source_url,
        status="creating",
        created_by_user_id=current_user.id,
    )
    db.add(child)
    await db.flush()

    result = await db.execute(select(SnapshotWorkItem).where(SnapshotWorkItem.snapshot_id == parent.id))
    parent_items = list(result.scalars().all())
    selected: set[int] = set(body.selected_azure_ids)

    azure_id_to_new_pk: dict[int, uuid.UUID] = {}
    for item in parent_items:
        row = SnapshotWorkItem(
            snapshot_id=child.id,
            azure_work_item_id=item.azure_work_item_id,
            work_item_type=item.work_item_type,
            title=item.title,
            state=item.state,
            parent_azure_work_item_id=item.parent_azure_work_item_id,
            area_path=item.area_path,
            iteration_path=item.iteration_path,
            order_index=item.order_index,
            revision=item.revision,
            changed_at=item.changed_at,
            is_selected=item.azure_work_item_id in selected,
            raw_fields=item.raw_fields,
            description_html=item.description_html,
            acceptance_criteria=item.acceptance_criteria,
            tags=item.tags,
            priority=item.priority,
            provenance=item.provenance,
            azure_url=item.azure_url,
        )
        db.add(row)
        await db.flush()
        azure_id_to_new_pk[item.azure_work_item_id] = row.id

    for item in parent_items:
        if item.parent_azure_work_item_id is not None and item.parent_azure_work_item_id in azure_id_to_new_pk:
            child_row = await db.get(SnapshotWorkItem, azure_id_to_new_pk[item.azure_work_item_id])
            if child_row is None:
                continue  # inserted moments ago in this same transaction — should be unreachable
            child_row.parent_id = azure_id_to_new_pk[item.parent_azure_work_item_id]
            db.add(child_row)

    relations_result = await db.execute(select(SnapshotRelation).where(SnapshotRelation.snapshot_id == parent.id))
    for relation in relations_result.scalars().all():
        db.add(
            SnapshotRelation(
                snapshot_id=child.id,
                source_azure_id=relation.source_azure_id,
                target_azure_id=relation.target_azure_id,
                relation_type=relation.relation_type,
            )
        )

    # Copy EVERY asset forward — not just ones for the new selection — so an
    # item deselected now and reselected in a later fork still has its
    # images, without ever touching Azure DevOps again.
    assets_result = await db.execute(
        select(Asset).where(Asset.snapshot_id == parent.id, Asset.download_status == "completed")
    )
    manifest_entries: list[dict] = []
    for asset in assets_result.scalars().all():
        if asset.snapshot_work_item_id is None:
            continue
        parent_item = next((i for i in parent_items if i.id == asset.snapshot_work_item_id), None)
        if parent_item is None or parent_item.azure_work_item_id not in azure_id_to_new_pk:
            continue

        new_asset_id = uuid.uuid4()
        new_key = source_asset_key(
            str(project.tenant_id), str(project.id), str(child.id), str(new_asset_id), asset.original_filename or "asset"
        )
        minio.copy_object(src_bucket=asset.bucket, src_key=asset.object_key, dst_bucket=asset.bucket, dst_key=new_key)

        new_asset = Asset(
            id=new_asset_id,
            tenant_id=project.tenant_id,
            srs_project_id=project.id,
            snapshot_id=child.id,
            snapshot_work_item_id=azure_id_to_new_pk[parent_item.azure_work_item_id],
            asset_kind=asset.asset_kind,
            bucket=asset.bucket,
            object_key=new_key,
            content_type=asset.content_type,
            byte_size=asset.byte_size,
            original_filename=asset.original_filename,
            source_url=asset.source_url,
            azure_relation_type=asset.azure_relation_type,
            sha256_hash=asset.sha256_hash,
            download_status="completed",
        )
        db.add(new_asset)
        manifest_entries.append(
            {"asset_id": str(new_asset.id), "bucket": new_asset.bucket, "object_key": new_asset.object_key, "sha256": new_asset.sha256_hash}
        )

    await db.flush()

    child.manifest = {
        "assets": manifest_entries,
        "work_item_hash": hashlib.sha256(
            "|".join(sorted(str(i) for i in selected)).encode()
        ).hexdigest(),
    }
    new_selected_items = [item for item in parent_items if item.azure_work_item_id in selected]
    child.root_work_item_ids = [
        item.azure_work_item_id for item in new_selected_items if item.parent_azure_work_item_id is None
    ]
    child.status = "sealed"
    child.sealed_at = datetime.now(timezone.utc)
    db.add(child)
    await db.commit()

    return BranchResponse(snapshot_id=child.id)
