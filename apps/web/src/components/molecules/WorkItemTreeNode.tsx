"use client";

import { useState } from "react";
import type { WorkItemNode } from "@/lib/types";
import { Badge } from "@/components/atoms/Badge";
import { stateTone } from "@/lib/workItemState";

interface Props {
  node: WorkItemNode;
  onToggle: (azureId: number, selected: boolean) => void;
  depth?: number;
}

const TYPE_TONE: Record<string, "accent" | "info" | "success" | "neutral" | "error"> = {
  epic: "accent",
  feature: "info",
  "user story": "success",
  story: "success",
  task: "neutral",
  bug: "error",
};

function toneForType(type: string) {
  return TYPE_TONE[type.toLowerCase()] ?? "neutral";
}

export function WorkItemTreeNode({ node, onToggle, depth = 0 }: Props) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div className="group flex items-start gap-2.5 rounded-md py-1.5 pl-1 pr-2 transition-colors hover:bg-surface-sunken">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-label={expanded ? "Collapse" : "Expand"}
            aria-expanded={expanded}
            className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-ink-faint transition-transform duration-150 hover:text-ink"
          >
            <svg
              viewBox="0 0 12 12"
              fill="none"
              className={`h-2.5 w-2.5 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
            >
              <path d="M4 2l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : (
          <span className="mt-0.5 h-4 w-4 shrink-0" />
        )}
        <input
          type="checkbox"
          checked={node.is_selected}
          onChange={(e) => onToggle(node.azure_work_item_id, e.target.checked)}
          className="mt-1 h-3.5 w-3.5 shrink-0 rounded-sm border-line-strong"
          style={{ accentColor: "var(--color-accent)" }}
        />
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
          <Badge tone={toneForType(node.work_item_type)}>{node.work_item_type}</Badge>
          <span className="truncate text-[13.5px] text-ink">{node.title}</span>
          <span className="font-mono text-[11px] text-ink-faint">#{node.azure_work_item_id}</span>
          <Badge tone={stateTone(node.state)}>{node.state}</Badge>
        </div>
      </div>
      {hasChildren && expanded && (
        <ul className="ml-[1.4rem] border-l border-line pl-3">
          {node.children.map((child) => (
            <WorkItemTreeNode key={child.azure_work_item_id} node={child} onToggle={onToggle} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}
