"use client";

import { useEffect, useState } from "react";
import { JobProgress } from "@/components/organisms/JobProgress";
import { DownloadDocumentCard } from "@/components/organisms/DownloadDocumentCard";
import { Card } from "@/components/atoms/Card";
import { apiClient } from "@/lib/api-client";
import { TERMINAL_STATUSES, useJobEventSource } from "@/hooks/useJobEventSource";

interface GeneratedDocumentSummary {
  id: string;
  format: string;
  asset_id: string;
}

export function JobWatchTemplate({ snapshotId, jobId }: { snapshotId: string; jobId: string }) {
  const [documents, setDocuments] = useState<GeneratedDocumentSummary[]>([]);
  const { job } = useJobEventSource(jobId);
  const jobStatus = job?.status;

  useEffect(() => {
    let cancelled = false;

    async function fetchDocuments() {
      try {
        const docs = await apiClient.get<GeneratedDocumentSummary[]>(`/snapshots/${snapshotId}/documents`);
        if (!cancelled) setDocuments(docs);
      } catch {
        // generation still running
      }
    }

    // Always fetch immediately on mount / whenever the job's status changes
    // (e.g. the moment it goes terminal) — the DOCX row commits well before
    // the PDF row does in the same worker chain, so stopping after the
    // first non-empty response (the old bug) meant the PDF card never
    // appeared. Keep polling until the job itself is done, not until the
    // list is merely non-empty.
    fetchDocuments();
    if (jobStatus && TERMINAL_STATUSES.has(jobStatus)) {
      return () => {
        cancelled = true;
      };
    }

    const poll = setInterval(fetchDocuments, 3000);
    return () => {
      cancelled = true;
      clearInterval(poll);
    };
  }, [snapshotId, jobStatus]);

  return (
    <div className="animate-fade-up space-y-6">
      <div className="space-y-3">
        <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">
          Step 4 — Watch
        </span>
        <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink">Generation progress.</h1>
        <p className="font-mono text-xs text-ink-faint">job {jobId}</p>
      </div>

      <Card>
        <JobProgress jobId={jobId} jobType="generate" />
      </Card>

      {documents.length > 0 && (
        <div className="animate-fade-up space-y-2">
          <h2 className="text-sm font-medium text-ink-muted">Generated documents</h2>
          {documents.map((doc) => (
            <DownloadDocumentCard key={doc.id} assetId={doc.asset_id} format={doc.format} />
          ))}
        </div>
      )}
    </div>
  );
}
