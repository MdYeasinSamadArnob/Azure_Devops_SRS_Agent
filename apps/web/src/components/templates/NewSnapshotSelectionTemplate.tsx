"use client";

import { Card } from "@/components/atoms/Card";
import { JobProgress } from "@/components/organisms/JobProgress";
import { SnapshotSelectionTemplate } from "@/components/templates/SnapshotSelectionTemplate";
import { useJobDiscoverySelection } from "@/hooks/useJobDiscoverySelection";

export function NewSnapshotSelectionTemplate({ projectId, jobId }: { projectId: string; jobId: string | null }) {
  const { roots, unlinkedCount, isSubmitting, error, updateRoots, submit } = useJobDiscoverySelection(
    jobId,
    projectId,
  );

  if (!jobId) {
    return <p className="text-sm text-ink-faint">Missing discovery job — start from the import page.</p>;
  }

  return (
    <SnapshotSelectionTemplate
      eyebrow="Step 2 — Select"
      title="Choose what to include."
      subtitle={<p className="font-mono text-xs text-ink-faint">job {jobId}</p>}
      roots={roots}
      onRootsChange={updateRoots}
      unlinkedCount={unlinkedCount}
      loadingSlot={
        <Card>
          <JobProgress jobId={jobId} jobType="import" />
        </Card>
      }
      error={error}
      footerNote="Sealing locks this selection into an immutable snapshot — generate as many documents from it as you like."
      submitLabel="Seal snapshot"
      submittingLabel="Sealing…"
      isSubmitting={isSubmitting}
      onSubmit={submit}
    />
  );
}
