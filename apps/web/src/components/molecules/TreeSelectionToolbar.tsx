"use client";

import { Button } from "@/components/atoms/Button";

interface Props {
  onSelectAll: () => void;
  onSelectNone: () => void;
  onSelectEpicsFeaturesStories: () => void;
  removeTasks: boolean;
  onRemoveTasksChange: (checked: boolean) => void;
  selectedCount: number;
  totalCount: number;
  submitLabel: string;
  submittingLabel: string;
  isSubmitting: boolean;
  submitDisabled: boolean;
  onSubmit: () => void;
}

export function TreeSelectionToolbar({
  onSelectAll,
  onSelectNone,
  onSelectEpicsFeaturesStories,
  removeTasks,
  onRemoveTasksChange,
  selectedCount,
  totalCount,
  submitLabel,
  submittingLabel,
  isSubmitting,
  submitDisabled,
  onSubmit,
}: Props) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
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
        <label className="flex cursor-pointer items-center gap-1.5 px-1 text-sm text-ink-muted">
          <input
            type="checkbox"
            checked={removeTasks}
            onChange={(e) => onRemoveTasksChange(e.target.checked)}
            className="h-3.5 w-3.5 shrink-0 rounded-sm border-line-strong"
            style={{ accentColor: "var(--color-accent)" }}
          />
          Remove Tasks
        </label>
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-ink-faint">
          {selectedCount} / {totalCount} selected
        </span>
        <Button onClick={onSubmit} disabled={submitDisabled} className="shrink-0 whitespace-nowrap">
          {isSubmitting ? submittingLabel : submitLabel}
        </Button>
      </div>
    </div>
  );
}
