"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient, ApiError } from "@/lib/api-client";
import { collectSelectedIds } from "@/lib/tree-selection";
import type { DiscoveryTreeResponse, WorkItemNode } from "@/lib/types";

/**
 * Data orchestration for the "reselect & regenerate" flow: loads an
 * already-sealed snapshot's full tree once, then forks a new snapshot from
 * the edited selection via /snapshots/{id}/branch (never re-hits Azure
 * DevOps — see snapshot_selection.py). Pairs with SnapshotSelectionTemplate,
 * the same presentational component useJobDiscoverySelection's page uses.
 */
export function useSnapshotReselection(snapshotId: string, projectId: string) {
  const router = useRouter();
  const [roots, setRoots] = useState<WorkItemNode[] | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .get<DiscoveryTreeResponse>(`/snapshots/${snapshotId}/tree`)
      .then((tree) => setRoots(tree.roots))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load this snapshot's tree"));
  }, [snapshotId]);

  function updateRoots(updater: (prev: WorkItemNode[]) => WorkItemNode[]) {
    setRoots((prev) => (prev ? updater(prev) : prev));
  }

  async function submit() {
    if (!roots) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const { snapshot_id } = await apiClient.post<{ snapshot_id: string }>(`/snapshots/${snapshotId}/branch`, {
        selected_azure_ids: collectSelectedIds(roots),
      });
      router.push(`/projects/${projectId}/snapshots/${snapshot_id}/generate`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update the selection");
    } finally {
      setIsSubmitting(false);
    }
  }

  return { roots, isSubmitting, error, updateRoots, submit };
}
