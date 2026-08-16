"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Card } from "@/components/atoms/Card";
import { TextField } from "@/components/atoms/TextField";
import { apiClient, ApiError } from "@/lib/api-client";

interface DiscoverResponse {
  job_id: string;
  srs_project_id: string;
}

/**
 * The PAT is submitted once over this form and never re-displayed or kept
 * client-side afterward — only the resulting connection_id/job_id survive
 * navigation. The API stores the PAT encrypted; it never echoes it back.
 */
export function AzureConnectionForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [pat, setPat] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const { job_id, srs_project_id } = await apiClient.post<DiscoverResponse>("/import/discover", {
        source_url: url,
        pat,
      });
      setPat(""); // never held in memory longer than the request that used it
      router.push(`/projects/${srs_project_id}/snapshots/new?jobId=${job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start discovery");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="max-w-xl">
      <form onSubmit={handleSubmit} className="space-y-5">
        <TextField
          label="Azure DevOps URL"
          id="ado-url"
          type="url"
          required
          monospace
          placeholder="https://dev.azure.com/your-org/your-project/_backlogs/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <TextField
          label="Personal access token"
          id="pat"
          type="password"
          required
          autoComplete="off"
          value={pat}
          onChange={(e) => setPat(e.target.value)}
          helperText="Stored encrypted. Never displayed again after this submission."
        />
        {error && (
          <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
            {error}
          </p>
        )}
        <Button type="submit" disabled={isSubmitting} className="w-full sm:w-auto">
          {isSubmitting ? "Starting discovery…" : "Discover work items"}
        </Button>
      </form>
    </Card>
  );
}
