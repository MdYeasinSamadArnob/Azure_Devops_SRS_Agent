from enum import StrEnum


class JobType(StrEnum):
    IMPORT = "import"
    GENERATE = "generate"
    ASSET_RETRY = "asset_retry"
    CONVERT = "convert"


class JobControlState(StrEnum):
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RETRYING = "retrying"


class ImportStage(StrEnum):
    QUEUED = "queued"
    AUTHENTICATING = "authenticating"
    DISCOVERING_FIELDS = "discovering_fields"
    FETCHING_HIERARCHY = "fetching_hierarchy"
    FETCHING_WORK_ITEMS = "fetching_work_items"
    DOWNLOADING_ASSETS = "downloading_assets"
    CREATING_SNAPSHOT = "creating_snapshot"
    COMPLETED = "completed"


class GenerateStage(StrEnum):
    QUEUED = "queued"
    NORMALIZING_CONTENT = "normalizing_content"
    RUNNING_LLM_RULES = "running_llm_rules"
    RENDERING_DOCX = "rendering_docx"
    CONVERTING_PDF = "converting_pdf"
    VERIFYING_DOCUMENT = "verifying_document"
    COMPLETED = "completed"


class SnapshotStatus(StrEnum):
    CREATING = "creating"
    VALIDATING = "validating"
    SEALED = "sealed"
    FAILED = "failed"


class ProvenanceTag(StrEnum):
    SOURCE_EXTRACTED = "source_extracted"
    SOURCE_REWRITTEN = "source_rewritten"
    AI_INFERRED = "ai_inferred"
    AI_PROPOSED = "ai_proposed"
    HUMAN_APPROVED = "human_approved"


class AssetKind(StrEnum):
    SOURCE_ATTACHMENT = "source_attachment"
    GENERATED_DOCUMENT = "generated_document"
    SNAPSHOT_MANIFEST = "snapshot_manifest"
    PREVIEW = "preview"
    TEMPLATE = "template"


class DownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class DocumentFormat(StrEnum):
    DOCX = "docx"
    PDF = "pdf"
    HTML = "html"


BUCKET_SOURCE_ASSETS = "srs-source-assets"
BUCKET_TEMPLATES = "srs-templates"
BUCKET_GENERATED_DOCUMENTS = "srs-generated-documents"
BUCKET_PREVIEWS = "srs-previews"
BUCKET_SNAPSHOTS = "srs-snapshots"
BUCKET_TEMPORARY = "srs-temporary"

ALL_BUCKETS = (
    BUCKET_SOURCE_ASSETS,
    BUCKET_TEMPLATES,
    BUCKET_GENERATED_DOCUMENTS,
    BUCKET_PREVIEWS,
    BUCKET_SNAPSHOTS,
    BUCKET_TEMPORARY,
)
