"use client";

import { Button } from "@/components/atoms/Button";

interface Props {
  onSelectAll: () => void;
  onSelectNone: () => void;
  onSelectEpicsFeaturesStories: () => void;
  selectedCount: number;
  totalCount: number;
}

export function TreeSelectionToolbar({
  onSelectAll,
  onSelectNone,
  onSelectEpicsFeaturesStories,
  selectedCount,
  totalCount,
}: Props) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onSelectAll} type="button">
          Select all
        </Button>
        <Button variant="ghost" size="sm" onClick={onSelectNone} type="button">
          Select none
        </Button>
        <Button variant="ghost" size="sm" onClick={onSelectEpicsFeaturesStories} type="button">
          Epics, Features &amp; Stories only
        </Button>
      </div>
      <span className="font-mono text-xs text-ink-faint">
        {selectedCount} / {totalCount} selected
      </span>
    </div>
  );
}
