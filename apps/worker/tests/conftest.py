import struct
import sys
import uuid
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest
from srs_core.crypto import SecretBox
from srs_core.db.models import (
    Asset,
    AzureConnection,
    ImportJob,
    JobEvent,
    SnapshotRelation,
    SnapshotWorkItem,
    SourceSnapshot,
    SrsProject,
    Tenant,
)

from src.config import get_worker_settings
from src.db import SessionLocal
from src.tasks import import_pipeline

def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data))


def _build_minimal_png() -> bytes:
    """A genuinely well-formed 1x1 grayscale PNG — needs to survive
    python-docx's own PNG chunk parsing when embedding it, not just
    round-trip as opaque bytes through MinIO.
    """
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    raw_scanline = b"\x00\x00"  # filter byte + one grayscale pixel
    idat = _png_chunk(b"IDAT", zlib.compress(raw_scanline))
    iend = _png_chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


# Needs to be a genuinely well-formed image since python-docx parses PNG
# chunk structure when embedding it (not just round-tripping bytes through
# MinIO).
FAKE_PNG_BYTES = _build_minimal_png()

RAW_WORK_ITEMS = {
    # Real Azure responses are bidirectional: a parent carries Hierarchy-Forward
    # relations to each child, and each child separately carries a
    # Hierarchy-Reverse relation back to its parent — fetch_hierarchy_from_roots
    # walks Forward from the roots, so that's the direction that matters here.
    101: {
        "id": 101,
        "fields": {"System.WorkItemType": "Epic", "System.Title": "Epic One", "System.State": "New"},
        "relations": [
            {"rel": "System.LinkTypes.Hierarchy-Forward", "url": "https://dev.azure.com/org/proj/_apis/wit/workItems/102"}
        ],
    },
    102: {
        "id": 102,
        "fields": {"System.WorkItemType": "Feature", "System.Title": "Feature Two", "System.State": "New"},
        "relations": [
            {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": "https://dev.azure.com/org/proj/_apis/wit/workItems/101"},
            {"rel": "System.LinkTypes.Hierarchy-Forward", "url": "https://dev.azure.com/org/proj/_apis/wit/workItems/103"},
        ],
    },
    103: {
        "id": 103,
        "fields": {"System.WorkItemType": "User Story", "System.Title": "Story Three", "System.State": "New"},
        "relations": [
            {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": "https://dev.azure.com/org/proj/_apis/wit/workItems/102"},
            {
                "rel": "AttachedFile",
                "url": "https://dev.azure.com/org/proj/_apis/wit/attachments/fake-guid?fileName=diagram.png",
                "attributes": {"name": "diagram.png"},
            },
        ],
    },
}


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def default_tenant(db_session) -> Tenant:
    tenant = db_session.query(Tenant).filter(Tenant.slug == "default").one()
    return tenant


@pytest.fixture
def azure_mocks(monkeypatch):
    async def fake_validate_access(self):
        return None

    async def fake_get_work_items_batch(self, ids, fields=None, on_omitted=None):
        return [RAW_WORK_ITEMS[i] for i in ids if i in RAW_WORK_ITEMS]

    async def fake_list_team_backlogs(self, team):
        return [{"id": "Microsoft.EpicCategory", "name": "Epics"}]

    async def fake_get_backlog_root_ids(self, team, backlog_id):
        # Mirrors the real Team Backlog API: only the Epic-level roots for
        # this team, not every work item in the project.
        return [101]

    async def fake_aclose(self):
        return None

    monkeypatch.setattr(import_pipeline.AzureDevOpsClient, "validate_access", fake_validate_access)
    monkeypatch.setattr(import_pipeline.AzureDevOpsClient, "get_work_items_batch", fake_get_work_items_batch)
    monkeypatch.setattr(import_pipeline.AzureDevOpsClient, "list_team_backlogs", fake_list_team_backlogs)
    monkeypatch.setattr(import_pipeline.AzureDevOpsClient, "get_backlog_root_ids", fake_get_backlog_root_ids)
    monkeypatch.setattr(import_pipeline.AzureDevOpsClient, "aclose", fake_aclose)

    def fake_transport_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FAKE_PNG_BYTES, headers={"content-type": "image/png"})

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(fake_transport_handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(import_pipeline, "httpx", httpx)
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient, raising=False)
    yield


@pytest.fixture
def fixture_import_job(db_session, default_tenant):
    unique = uuid.uuid4().hex[:8]
    project = SrsProject(
        tenant_id=default_tenant.id,
        name=f"test-{unique}",
        azure_org=f"test-org-{unique}",
        azure_project="proj",
        azure_base_url="https://dev.azure.com/test-org/proj",
    )
    db_session.add(project)
    db_session.flush()

    secret_box = SecretBox(get_worker_settings().pat_encryption_key)
    connection = AzureConnection(
        tenant_id=default_tenant.id,
        srs_project_id=project.id,
        auth_type="pat",
        encrypted_pat=secret_box.encrypt("fake-pat-value"),
        azure_org=project.azure_org,
        azure_project=project.azure_project,
    )
    db_session.add(connection)
    db_session.flush()

    import_job = ImportJob(
        tenant_id=default_tenant.id,
        srs_project_id=project.id,
        azure_connection_id=connection.id,
        status="queued",
        stage="queued",
        params={"team": "TestTeam", "backlog_level": "Epics", "work_item_id": None},
    )
    db_session.add(import_job)
    db_session.flush()

    snapshot = SourceSnapshot(
        srs_project_id=project.id,
        import_job_id=import_job.id,
        source_url="https://dev.azure.com/test-org/proj",
        status="creating",
    )
    db_session.add(snapshot)
    db_session.commit()

    yield import_job, snapshot, connection

    # Cleanup — this is a throwaway dev DB but keep it tidy across test runs.
    db_session.query(JobEvent).filter(JobEvent.job_id == import_job.id).delete()
    db_session.query(Asset).filter(Asset.snapshot_id == snapshot.id).delete()
    db_session.query(SnapshotRelation).filter(SnapshotRelation.snapshot_id == snapshot.id).delete()
    db_session.query(SnapshotWorkItem).filter(SnapshotWorkItem.snapshot_id == snapshot.id).delete()
    db_session.query(SourceSnapshot).filter(SourceSnapshot.id == snapshot.id).delete()
    db_session.query(ImportJob).filter(ImportJob.id == import_job.id).delete()
    db_session.query(AzureConnection).filter(AzureConnection.id == connection.id).delete()
    db_session.query(SrsProject).filter(SrsProject.id == project.id).delete()
    db_session.commit()
