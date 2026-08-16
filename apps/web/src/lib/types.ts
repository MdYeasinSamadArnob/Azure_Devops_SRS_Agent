// Hand-written for Increment 1; replaced by generated packages/contracts types in Phase 1's
// later increments once the OpenAPI schema is stable enough to codegen from.

export type ImportStage =
  | "queued"
  | "authenticating"
  | "discovering_fields"
  | "fetching_hierarchy"
  | "fetching_work_items"
  | "downloading_assets"
  | "creating_snapshot"
  | "completed";

export type GenerateStage =
  | "queued"
  | "normalizing_content"
  | "running_llm_rules"
  | "rendering_docx"
  | "converting_pdf"
  | "verifying_document"
  | "completed";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface JobSummary {
  id: string;
  job_type: "import" | "generate" | "asset_retry" | "convert";
  status: JobStatus;
  stage: ImportStage | GenerateStage | string;
  progress_percent: number;
  error_message?: string | null;
}

export interface WorkItemNode {
  azure_work_item_id: number;
  work_item_type: string;
  title: string;
  state: string;
  is_selected: boolean;
  children: WorkItemNode[];
}

// Shared by both the job-scoped discovery tree (/import/{jobId}/tree) and
// the snapshot-scoped tree (/snapshots/{snapshotId}/tree) — same shape,
// different data source.
export interface DiscoveryTreeResponse {
  roots: WorkItemNode[];
  unlinked_count: number;
  snapshot_id: string | null;
}

export interface HealthCheckResponse {
  status: "ok" | "degraded";
  checks?: Record<string, string>;
}
