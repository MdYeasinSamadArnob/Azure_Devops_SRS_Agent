"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiClient, ApiError } from "@/lib/api-client";
import { collectSelectedIds } from "@/lib/tree-selection";
import type { DiscoveryTreeResponse, WorkItemNode } from "@/lib/types";

/**
 * Data orchestration for the "new snapshot" selection flow: polls a
 * still-running import job's discovery tree until it's populated, then
 * seals the final selection into a snapshot. Pairs with
 * SnapshotSelectionTemplate, which owns the shared presentational markup
 * also used by useSnapshotReselection.
 */
export function useJobDiscoverySelection(jobId: string | null, projectId: string) {
  const router = useRouter();
  const [roots, setRoots] = useState<WorkItemNode[] | null>(null);
  const [unlinkedCount, setUnlinkedCount] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const poll = setInterval(async () => {
      try {
        const tree = await apiClient.get<DiscoveryTreeResponse>(`/import/${jobId}/tree`);
        if (!cancelled && tree.roots.length > 0) {
          setRoots(tree.roots);
          setUnlinkedCount(tree.unlinked_count);
          clearInterval(poll);
        }
      } catch {
        // discovery still running or not yet available
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(poll);
    };
  }, [jobId]);

  function updateRoots(updater: (prev: WorkItemNode[]) => WorkItemNode[]) {
    setRoots((prev) => (prev ? updater(prev) : prev));
  }

  async function submit() {
    if (!jobId || !roots) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const { snapshot_id } = await apiClient.post<{ snapshot_id: string }>(`/import/${jobId}/seal`, {
        selected_azure_ids: collectSelectedIds(roots),
      });
      router.push(`/projects/${projectId}/snapshots/${snapshot_id}/generate`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to seal snapshot");
    } finally {
      setIsSubmitting(false);
    }
  }

  return { roots, unlinkedCount, isSubmitting, error, updateRoots, submit };
}
