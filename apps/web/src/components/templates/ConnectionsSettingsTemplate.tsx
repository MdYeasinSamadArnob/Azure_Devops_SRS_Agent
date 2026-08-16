"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/atoms/Card";
import { Skeleton } from "@/components/atoms/Skeleton";
import { apiClient, ApiError } from "@/lib/api-client";

interface ConnectionListItem {
  id: string;
  azure_org: string;
  azure_project: string;
  created_at: string;
}

export function ConnectionsSettingsTemplate() {
  const [connections, setConnections] = useState<ConnectionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<ConnectionListItem[]>("/connections")
      .then(setConnections)
      .catch(() => setConnections([]));
  }, []);

  async function handleRemove(id: string) {
    setRemovingId(id);
    setError(null);
    try {
      await apiClient.delete(`/connections/${id}`);
      setConnections((prev) => (prev ? prev.filter((c) => c.id !== id) : prev));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove connection");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div className="space-y-8 pt-6">
      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">Your PATs</h2>
        <p className="max-w-lg text-sm leading-relaxed text-ink-muted">
          Every Azure DevOps personal access token you have submitted, stored encrypted. The token itself is
          never displayed again after submission — only remove and re-add if it needs to change.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </p>
      )}

      {connections === null ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : connections.length === 0 ? (
        <p className="text-sm text-ink-faint">No connections yet — add one from the project import form.</p>
      ) : (
        <div className="space-y-3">
          {connections.map((connection) => (
            <Card key={connection.id}>
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">
                    {connection.azure_org}/{connection.azure_project}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-ink-faint">
                    Added {new Date(connection.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleRemove(connection.id)}
                  disabled={removingId === connection.id}
                  className="shrink-0 rounded-md px-2.5 py-1.5 text-xs font-medium text-error transition-colors hover:bg-error/10 disabled:opacity-50"
                >
                  {removingId === connection.id ? "Removing…" : "Remove"}
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
