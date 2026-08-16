"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/atoms/Badge";
import { Card } from "@/components/atoms/Card";
import { Skeleton } from "@/components/atoms/Skeleton";
import { DownloadDocumentCard } from "@/components/organisms/DownloadDocumentCard";
import { apiClient } from "@/lib/api-client";

interface GeneratedDocumentItem {
  format: string;
  asset_id: string;
}

interface GenerationHistoryItem {
  generation_job_id: string;
  snapshot_id: string;
  status: string;
  error_message: string | null;
  formats: string[];
  document_metadata: Record<string, string>;
  created_at: string;
  documents: GeneratedDocumentItem[];
}

const STATUS_TONE: Record<string, "success" | "error" | "info" | "neutral"> = {
  completed: "success",
  failed: "error",
  running: "info",
  queued: "neutral",
};

export function GenerationHistoryTemplate({ projectId }: { projectId: string }) {
  const [generations, setGenerations] = useState<GenerationHistoryItem[] | null>(null);

  useEffect(() => {
    apiClient
      .get<GenerationHistoryItem[]>(`/projects/${projectId}/generations`)
      .then(setGenerations)
      .catch(() => setGenerations([]));
  }, [projectId]);

  return (
    <div className="animate-fade-up space-y-8">
      <div className="space-y-3">
        <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">
          Version history
        </span>
        <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink sm:text-4xl">
          Generated documents
        </h1>
        <p className="max-w-lg text-[15px] leading-relaxed text-ink-muted">
          Every past generation for this project — each one keeps its own downloadable documents, never
          overwritten by a later regeneration.
        </p>
      </div>

      {generations === null ? (
        <div className="space-y-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : generations.length === 0 ? (
        <p className="text-sm text-ink-faint">No documents generated for this project yet.</p>
      ) : (
        <div className="space-y-4">
          {generations.map((gen) => (
            <Card key={gen.generation_job_id}>
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-ink">
                      {gen.document_metadata.app_name || "Untitled document"}
                      {gen.document_metadata.version && (
                        <span className="ml-2 font-mono text-xs text-ink-faint">v{gen.document_metadata.version}</span>
                      )}
                    </p>
                    <p className="mt-0.5 font-mono text-[11px] text-ink-faint">
                      {new Date(gen.created_at).toLocaleString()}
                      {gen.document_metadata.owner && ` · ${gen.document_metadata.owner}`}
                    </p>
                  </div>
                  <Badge tone={STATUS_TONE[gen.status] ?? "neutral"}>{gen.status}</Badge>
                </div>
                {gen.error_message && <p className="text-xs text-error">{gen.error_message}</p>}
                {gen.documents.length > 0 && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {gen.documents.map((doc) => (
                      <DownloadDocumentCard key={doc.asset_id} assetId={doc.asset_id} format={doc.format} />
                    ))}
                  </div>
                )}
                <Link
                  href={`/projects/${projectId}/snapshots/${gen.snapshot_id}/reselect`}
                  className="inline-block text-xs font-medium text-accent transition-colors hover:text-accent-hover"
                >
                  Reselect &amp; regenerate →
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
