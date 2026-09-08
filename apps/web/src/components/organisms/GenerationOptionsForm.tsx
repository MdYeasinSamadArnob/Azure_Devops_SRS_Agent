"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Card } from "@/components/atoms/Card";
import { TextField } from "@/components/atoms/TextField";
import { apiClient, ApiError } from "@/lib/api-client";

interface GenerateResponse {
  job_id: string;
}

const FORMAT_OPTIONS = [
  { key: "docx" as const, label: "DOCX", description: "Editable Word document" },
  { key: "pdf" as const, label: "PDF", description: "Print-ready, requires DOCX render first" },
];

// Matches the new SRS template's 1.1 Document Information table exactly
// (11 fields - see docs/srs-content-mapping-spec.md and backlog task-6).
// Every field is optional: nothing here is required to start a generation,
// matching the template's own "leave it blank, fill in by hand later"
// convention for anything not supplied.
interface DocumentMetadata {
  document_id: string;
  module_code: string;
  document_title: string;
  document_owner: string;
  related_brd: string;
  date_created: string;
  date_submitted: string;
  document_status: "Draft" | "Final";
  document_version: string;
  classification: string;
  review_cycle: string;
  // Not one of the 1.1 table's 11 fields, but the new template's cover
  // page needs it (the old template has no equivalent).
  client: string;
}

const DEFAULT_METADATA: DocumentMetadata = {
  document_id: "",
  module_code: "",
  document_title: "",
  document_owner: "",
  related_brd: "",
  date_created: "",
  date_submitted: "",
  document_status: "Draft",
  document_version: "0.1",
  classification: "CONFIDENTIAL",
  review_cycle: "Per change or on stakeholder request",
  client: "",
};

// "legacy" = the original org-template pipeline ("Generate Document").
// "v2" = the new ERA_SRS_Template_V2.1 pipeline ("Generate Formatted SRS") -
// a more organized document structure, still being built out section by
// section (see backlog task-15 and the tasks it gates).
type TemplateVersion = "legacy" | "v2";

export function GenerationOptionsForm({
  snapshotId,
  projectId,
  snapshotStatus,
}: {
  snapshotId: string;
  projectId: string;
  snapshotStatus: string;
}) {
  const router = useRouter();
  const [formats, setFormats] = useState<{ docx: boolean; pdf: boolean }>({ docx: true, pdf: true });
  const [metadata, setMetadata] = useState<DocumentMetadata>(DEFAULT_METADATA);
  // Which button is in flight, if any - tracked per-version (not a plain
  // boolean) so submitting one doesn't visually freeze the other button in
  // its own "Starting generation…" label while its own click never fired.
  const [submitting, setSubmitting] = useState<TemplateVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isSealed = snapshotStatus === "sealed";

  async function handleSubmit(templateVersion: TemplateVersion) {
    setSubmitting(templateVersion);
    setError(null);
    const selectedFormats = Object.entries(formats)
      .filter(([, checked]) => checked)
      .map(([format]) => format);
    try {
      const { job_id } = await apiClient.post<GenerateResponse>(`/snapshots/${snapshotId}/generate`, {
        formats: selectedFormats,
        document_metadata: metadata,
        template_version: templateVersion,
      });
      router.push(`/projects/${projectId}/snapshots/${snapshotId}/jobs/${job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start generation");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <Card className="max-w-xl">
      <form onSubmit={(event) => event.preventDefault()} className="space-y-5">
        {!isSealed && (
          <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            Generation is disabled until this snapshot is sealed (current status: {snapshotStatus}).
          </p>
        )}
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-ink">Document details</h3>
          <p className="text-xs text-ink-faint">
            Fills the Document Information table (section 1.1). Everything here is optional — anything left blank
            stays as a placeholder in the generated document for you to fill in by hand.
          </p>
          <TextField
            label="Document title"
            id="doc-title"
            placeholder="e.g. Loan Approval and Management System"
            value={metadata.document_title}
            onChange={(e) => setMetadata((m) => ({ ...m, document_title: e.target.value }))}
            helperText="Appears on the cover page, header, and Document Information table."
          />
          <TextField
            label="Client"
            id="doc-client"
            placeholder="[Client Name] — [Department Name]"
            value={metadata.client}
            onChange={(e) => setMetadata((m) => ({ ...m, client: e.target.value }))}
            helperText="Cover page only — not part of the Document Information table."
          />
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Document ID"
              id="doc-id"
              placeholder="[ProjectCode]_SRS_[MN-XXX]_V0.1"
              value={metadata.document_id}
              onChange={(e) => setMetadata((m) => ({ ...m, document_id: e.target.value }))}
            />
            <TextField
              label="Module code"
              id="doc-module-code"
              placeholder="MN-XXX"
              value={metadata.module_code}
              onChange={(e) => setMetadata((m) => ({ ...m, module_code: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Document owner"
              id="doc-owner"
              placeholder="Name, Role, Organization"
              value={metadata.document_owner}
              onChange={(e) => setMetadata((m) => ({ ...m, document_owner: e.target.value }))}
            />
            <TextField
              label="Related BRD"
              id="doc-related-brd"
              placeholder="[ProjectCode]_BRD_[MN-XXX]_Vx.x"
              value={metadata.related_brd}
              onChange={(e) => setMetadata((m) => ({ ...m, related_brd: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Date created"
              id="doc-date-created"
              type="date"
              value={metadata.date_created}
              onChange={(e) => setMetadata((m) => ({ ...m, date_created: e.target.value }))}
            />
            <TextField
              label="Date submitted"
              id="doc-date-submitted"
              type="date"
              value={metadata.date_submitted}
              onChange={(e) => setMetadata((m) => ({ ...m, date_submitted: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="doc-status" className="block text-sm font-medium text-ink">
                Document status
              </label>
              <select
                id="doc-status"
                value={metadata.document_status}
                onChange={(e) =>
                  setMetadata((m) => ({ ...m, document_status: e.target.value as "Draft" | "Final" }))
                }
                className="w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2.5 text-sm text-ink transition-colors duration-150 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              >
                <option value="Draft">Draft</option>
                <option value="Final">Final</option>
              </select>
            </div>
            <TextField
              label="Document version"
              id="doc-version"
              value={metadata.document_version}
              onChange={(e) => setMetadata((m) => ({ ...m, document_version: e.target.value }))}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Classification"
              id="doc-classification"
              value={metadata.classification}
              onChange={(e) => setMetadata((m) => ({ ...m, classification: e.target.value }))}
            />
            <TextField
              label="Review cycle"
              id="doc-review-cycle"
              value={metadata.review_cycle}
              onChange={(e) => setMetadata((m) => ({ ...m, review_cycle: e.target.value }))}
            />
          </div>
        </div>
        <div className="space-y-2">
          {FORMAT_OPTIONS.map((option) => (
            <label
              key={option.key}
              className="flex cursor-pointer items-start gap-3 rounded-md border border-line-strong p-3 transition-colors hover:bg-surface-sunken has-[:checked]:border-accent has-[:checked]:bg-accent/5"
            >
              <input
                type="checkbox"
                checked={formats[option.key]}
                onChange={(e) => setFormats((f) => ({ ...f, [option.key]: e.target.checked }))}
                className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-sm border-line-strong"
                style={{ accentColor: "var(--color-accent)" }}
              />
              <span>
                <span className="block text-sm font-medium text-ink">{option.label}</span>
                <span className="block text-xs text-ink-faint">{option.description}</span>
              </span>
            </label>
          ))}
        </div>
        {error && (
          <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
            {error}
          </p>
        )}
        <div className="space-y-2">
          {/* The "Generate Document" (legacy) button is hidden, not removed
              from the codebase - handleSubmit("legacy") and the "legacy"
              template_version path (API + worker) are untouched, so it can
              be brought back by re-adding the button below if needed:
              <Button type="button" onClick={() => handleSubmit("legacy")}
                disabled={!isSealed || submitting !== null || (!formats.docx && !formats.pdf)}
                className="w-full">
                {submitting === "legacy" ? "Starting generation…" : "Generate Document"}
              </Button> */}
          <Button
            type="button"
            onClick={() => handleSubmit("v2")}
            disabled={!isSealed || submitting !== null || (!formats.docx && !formats.pdf)}
            className="w-full"
          >
            {submitting === "v2" ? "Starting generation…" : "Generate Formatted SRS"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
