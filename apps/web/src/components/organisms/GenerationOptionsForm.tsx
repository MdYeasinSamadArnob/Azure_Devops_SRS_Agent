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

interface DocumentMetadata {
  app_name: string;
  version: string;
  owner: string;
  status: "Draft" | "Final";
  revision_note: string;
  footer_year: string;
}

const DEFAULT_METADATA: DocumentMetadata = {
  app_name: "",
  version: "0.1",
  owner: "",
  status: "Draft",
  revision_note: "Initial generation from Azure DevOps snapshot",
  footer_year: new Date().getFullYear().toString(),
};

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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isSealed = snapshotStatus === "sealed";

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const selectedFormats = Object.entries(formats)
      .filter(([, checked]) => checked)
      .map(([format]) => format);
    try {
      const { job_id } = await apiClient.post<GenerateResponse>(`/snapshots/${snapshotId}/generate`, {
        formats: selectedFormats,
        document_metadata: metadata,
      });
      router.push(`/projects/${projectId}/snapshots/${snapshotId}/jobs/${job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start generation");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="max-w-xl">
      <form onSubmit={handleSubmit} className="space-y-5">
        {!isSealed && (
          <p className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
            Generation is disabled until this snapshot is sealed (current status: {snapshotStatus}).
          </p>
        )}
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-ink">Document details</h3>
          <TextField
            label="App / product name"
            id="doc-app-name"
            required
            placeholder="e.g. Loan Approval and Management System"
            value={metadata.app_name}
            onChange={(e) => setMetadata((m) => ({ ...m, app_name: e.target.value }))}
            helperText="Appears on the cover page, header, and Document Information table."
          />
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Document version"
              id="doc-version"
              value={metadata.version}
              onChange={(e) => setMetadata((m) => ({ ...m, version: e.target.value }))}
            />
            <div className="space-y-1.5">
              <label htmlFor="doc-status" className="block text-sm font-medium text-ink">
                Document status
              </label>
              <select
                id="doc-status"
                value={metadata.status}
                onChange={(e) => setMetadata((m) => ({ ...m, status: e.target.value as "Draft" | "Final" }))}
                className="w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2.5 text-sm text-ink transition-colors duration-150 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
              >
                <option value="Draft">Draft</option>
                <option value="Final">Final</option>
              </select>
            </div>
          </div>
          <TextField
            label="Document owner / prepared by"
            id="doc-owner"
            placeholder="Optional"
            value={metadata.owner}
            onChange={(e) => setMetadata((m) => ({ ...m, owner: e.target.value }))}
          />
          <TextField
            label="Revision note"
            id="doc-revision-note"
            value={metadata.revision_note}
            onChange={(e) => setMetadata((m) => ({ ...m, revision_note: e.target.value }))}
            helperText="Seeds the first row of the Document History table."
          />
          <TextField
            label="Footer copyright year"
            id="doc-footer-year"
            value={metadata.footer_year}
            onChange={(e) => setMetadata((m) => ({ ...m, footer_year: e.target.value }))}
            helperText="Shown in the page footer: “Copyright © {year} ERA Info Tech Ltd.”"
          />
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
        <Button
          type="submit"
          disabled={!isSealed || isSubmitting || (!formats.docx && !formats.pdf) || !metadata.app_name.trim()}
        >
          {isSubmitting ? "Starting generation…" : "Generate document"}
        </Button>
      </form>
    </Card>
  );
}
