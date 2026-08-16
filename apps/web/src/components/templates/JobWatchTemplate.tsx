"use client";

import { useEffect, useState } from "react";
import { JobProgress } from "@/components/organisms/JobProgress";
import { DownloadDocumentCard } from "@/components/organisms/DownloadDocumentCard";
import { Card } from "@/components/atoms/Card";
import { apiClient } from "@/lib/api-client";

interface GeneratedDocumentSummary {
  id: string;
  format: string;
  asset_id: string;
}

export function JobWatchTemplate({ snapshotId, jobId }: { snapshotId: string; jobId: string }) {
  const [documents, setDocuments] = useState<GeneratedDocumentSummary[]>([]);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const docs = await apiClient.get<GeneratedDocumentSummary[]>(`/snapshots/${snapshotId}/documents`);
        if (docs.length > 0) {
          setDocuments(docs);
          clearInterval(poll);
        }
      } catch {
        // generation still running
      }
    }, 3000);
    return () => clearInterval(poll);
  }, [snapshotId]);

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
