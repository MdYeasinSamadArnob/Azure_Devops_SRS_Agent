from datetime import datetime, timezone

from srs_core.storage.minio_client import MinioClient, MinioSettings, build_document_filename


def test_presigned_urls_use_public_endpoint_not_internal_one():
    """A presigned URL signed with the internal Docker-network address
    (e.g. minio:9000) is unusable by a real browser — this was a real bug
    where every download link was broken outside the compose network.
    """
    client = MinioClient(
        MinioSettings(
            endpoint="minio:9000",
            access_key="test-access",
            secret_key="test-secret",
            public_endpoint="localhost:9020",
        )
    )

    url = client.presigned_get_url("some-bucket", "some/key.docx", original_filename="doc.docx")

    assert url.startswith("http://localhost:9020/")
    assert "minio:9000" not in url


def test_presigned_urls_fall_back_to_endpoint_when_no_public_endpoint_set():
    client = MinioClient(
        MinioSettings(
            endpoint="localhost:9020",
            access_key="test-access",
            secret_key="test-secret",
        )
    )

    url = client.presigned_get_url("some-bucket", "some/key.docx", original_filename="doc.docx")

    assert url.startswith("http://localhost:9020/")


def test_build_document_filename_sanitizes_title_and_appends_timestamp():
    generated_at = datetime(2026, 8, 17, 14, 32, 5, tzinfo=timezone.utc)

    filename = build_document_filename("Acme Inventory! v2", generated_at, "docx")

    assert filename == "Acme_Inventory_v2_20260817_143205.docx"


def test_build_document_filename_uses_the_given_extension():
    generated_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    assert build_document_filename("Title", generated_at, "pdf").endswith(".pdf")
    assert build_document_filename("Title", generated_at, "docx").endswith(".docx")
