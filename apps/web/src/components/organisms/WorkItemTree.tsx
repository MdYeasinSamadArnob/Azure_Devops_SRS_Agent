"use client";

import type { WorkItemNode } from "@/lib/types";
import { WorkItemTreeNode } from "@/components/molecules/WorkItemTreeNode";

interface Props {
  roots: WorkItemNode[];
  unlinkedCount?: number;
  onToggle: (azureId: number, selected: boolean) => void;
}

export function WorkItemTree({ roots, unlinkedCount = 0, onToggle }: Props) {
  if (roots.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line-strong px-4 py-8 text-center text-sm text-ink-faint">
        No work items discovered yet.
      </div>
    );
  }

  return (
    <div>
      {unlinkedCount > 0 && (
        <div className="mb-3 flex items-start gap-2 rounded-md border border-warning/25 bg-warning/10 px-3 py-2 text-xs text-warning">
          <svg viewBox="0 0 16 16" fill="none" className="mt-0.5 h-3.5 w-3.5 shrink-0">
            <path
              d="M8 1.5 1 14h14L8 1.5zM8 6v4M8 12h.01"
              stroke="currentColor"
              strokeWidth="1.3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span>
            {unlinkedCount} work item{unlinkedCount === 1 ? "" : "s"} fetched but not reachable from the selected
            roots — excluded from this tree.
          </span>
        </div>
      )}
      <ul className="rounded-lg border border-line bg-surface-raised p-2">
        {roots.map((node) => (
          <WorkItemTreeNode key={node.azure_work_item_id} node={node} onToggle={onToggle} />
        ))}
      </ul>
    </div>
  );
}
