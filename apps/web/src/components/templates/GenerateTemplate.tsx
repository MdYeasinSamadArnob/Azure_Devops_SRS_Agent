"use client";

import { useEffect, useState } from "react";
import { GenerationOptionsForm } from "@/components/organisms/GenerationOptionsForm";
import { ImportSummaryCard } from "@/components/organisms/ImportSummaryCard";
import { apiClient } from "@/lib/api-client";

interface SnapshotSummary {
  id: string;
  status: string;
  source_url: string;
}

const TERMINAL_STATUSES = new Set(["sealed", "failed"]);

export function GenerateTemplate({ projectId, snapshotId }: { projectId: string; snapshotId: string }) {
  const [snapshot, setSnapshot] = useState<SnapshotSummary | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const result = await apiClient.get<SnapshotSummary>(`/snapshots/${snapshotId}`);
        if (cancelled) return;
        setSnapshot(result);
        if (!TERMINAL_STATUSES.has(result.status)) {
          setTimeout(poll, 2000);
        }
      } catch {
        if (!cancelled) setTimeout(poll, 2000);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [snapshotId]);

  return (
    <div className="animate-fade-up space-y-6">
      <div className="space-y-3">
        <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">
          Step 3 — Generate
        </span>
        <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink">
          Produce the document.
        </h1>
      </div>
      {snapshot && <ImportSummaryCard sourceUrl={snapshot.source_url} status={snapshot.status} />}
      <GenerationOptionsForm
        snapshotId={snapshotId}
        projectId={projectId}
        snapshotStatus={snapshot?.status ?? "loading"}
      />
    </div>
  );
}
