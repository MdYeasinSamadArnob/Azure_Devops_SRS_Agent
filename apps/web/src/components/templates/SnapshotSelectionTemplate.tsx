"use client";

import { useMemo } from "react";
import { Button } from "@/components/atoms/Button";
import { TreeSelectionToolbar } from "@/components/molecules/TreeSelectionToolbar";
import { WorkItemTree } from "@/components/organisms/WorkItemTree";
import {
  EPIC_FEATURE_STORY_TYPES,
  collectSelectedIds,
  flattenIds,
  setSelectedByType,
  setSelectedEverywhere,
  toggleNode,
} from "@/lib/tree-selection";
import type { WorkItemNode } from "@/lib/types";

interface SnapshotSelectionTemplateProps {
  eyebrow: string;
  title: string;
  subtitle: React.ReactNode;
  roots: WorkItemNode[] | null;
  onRootsChange: (updater: (prev: WorkItemNode[]) => WorkItemNode[]) => void;
  unlinkedCount?: number;
  loadingSlot: React.ReactNode;
  error?: string | null;
  footerNote: React.ReactNode;
  submitLabel: string;
  submittingLabel: string;
  isSubmitting: boolean;
  onSubmit: () => void;
}

/**
 * Shared by the "new snapshot" (job-scoped, useJobDiscoverySelection) and
 * "reselect & regenerate" (snapshot-scoped, useSnapshotReselection) flows —
 * identical selection UI, different data source and submit action, which
 * their respective hooks own. This is the "template" layer: arranges
 * organisms/molecules from props, no data-fetching of its own.
 */
export function SnapshotSelectionTemplate({
  eyebrow,
  title,
  subtitle,
  roots,
  onRootsChange,
  unlinkedCount = 0,
  loadingSlot,
  error,
  footerNote,
  submitLabel,
  submittingLabel,
  isSubmitting,
  onSubmit,
}: SnapshotSelectionTemplateProps) {
  const selectedCount = useMemo(() => (roots ? collectSelectedIds(roots).length : 0), [roots]);

  function handleToggle(azureId: number, selected: boolean) {
    onRootsChange((prev) => toggleNode(prev, azureId, selected));
  }

  return (
    <div className="animate-fade-up space-y-6">
      <div className="space-y-3">
        <span className="font-mono text-xs font-medium uppercase tracking-[0.14em] text-accent">{eyebrow}</span>
        <h1 className="font-display text-3xl font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {subtitle}
      </div>

      {!roots && loadingSlot}

      {error && (
        <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
          {error}
        </p>
      )}

      {roots && (
        <>
          <TreeSelectionToolbar
            selectedCount={selectedCount}
            totalCount={flattenIds(roots).length}
            onSelectAll={() => onRootsChange((prev) => setSelectedEverywhere(prev, true))}
            onSelectNone={() => onRootsChange((prev) => setSelectedEverywhere(prev, false))}
            onSelectEpicsFeaturesStories={() => onRootsChange((prev) => setSelectedByType(prev, EPIC_FEATURE_STORY_TYPES))}
          />
          <WorkItemTree roots={roots} unlinkedCount={unlinkedCount} onToggle={handleToggle} />
          <div className="flex items-center justify-between border-t border-line pt-5">
            <p className="text-sm text-ink-faint">{footerNote}</p>
            <Button onClick={onSubmit} disabled={isSubmitting || selectedCount === 0} className="shrink-0">
              {isSubmitting ? submittingLabel : submitLabel}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
