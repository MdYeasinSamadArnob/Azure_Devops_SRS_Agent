"use client";

import { useState } from "react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { apiClient, ApiError } from "@/lib/api-client";

interface PresignedUrlResponse {
  url: string;
  expires_in_seconds: number;
  /** "minio" | "local_fallback" — the API transparently falls back to a
   * local-disk mirror when MinIO is unreachable; nothing to handle here. */
  source?: string;
}

const FORMAT_ICON: Record<string, string> = {
  docx: "📄",
  pdf: "📕",
};

/**
 * The browser never receives MinIO credentials — only a short-lived
 * presigned URL minted by the API after an authorization check.
 */
export function DownloadDocumentCard({ assetId, format }: { assetId: string; format: string }) {
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleDownload() {
    setIsLoading(true);
    setError(null);
    try {
      const { url } = await apiClient.get<PresignedUrlResponse>(`/assets/${assetId}/presigned-url`);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to get download link");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface-raised px-4 py-3 transition-colors hover:border-line-strong">
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className="text-lg leading-none">
          {FORMAT_ICON[format] ?? "📄"}
        </span>
        <Badge tone="neutral">{format}</Badge>
      </div>
      <div className="flex items-center gap-2">
        {error && (
          <span role="alert" className="text-xs text-error">
            {error}
          </span>
        )}
        <Button variant="secondary" size="sm" onClick={handleDownload} disabled={isLoading}>
          {isLoading ? "Preparing…" : "Download"}
        </Button>
      </div>
    </div>
  );
}
