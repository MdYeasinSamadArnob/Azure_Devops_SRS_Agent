"use client";

import { Skeleton } from "@/components/atoms/Skeleton";
import { SnapshotSelectionTemplate } from "@/components/templates/SnapshotSelectionTemplate";
import { useSnapshotReselection } from "@/hooks/useSnapshotReselection";

export function ReselectSnapshotTemplate({ projectId, snapshotId }: { projectId: string; snapshotId: string }) {
  const { roots, isSubmitting, error, updateRoots, submit } = useSnapshotReselection(snapshotId, projectId);

  return (
    <SnapshotSelectionTemplate
      eyebrow="Reselect & regenerate"
      title="Change what's included."
      subtitle={
        <p className="max-w-lg text-[15px] leading-relaxed text-ink-muted">
          Adjusting this selection never re-fetches from Azure DevOps — everything below was already imported.
          Items that were never previously included may render without their diagrams; start a fresh import if
          you need to pull in brand-new work items.
        </p>
      }
      roots={roots}
      onRootsChange={updateRoots}
      loadingSlot={
        <div className="space-y-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-64" />
        </div>
      }
      error={error}
      footerNote="Confirming forks a new, independent snapshot from this selection and takes you straight to generation."
      submitLabel="Apply & continue"
      submittingLabel="Applying selection…"
      isSubmitting={isSubmitting}
      onSubmit={submit}
    />
  );
}
