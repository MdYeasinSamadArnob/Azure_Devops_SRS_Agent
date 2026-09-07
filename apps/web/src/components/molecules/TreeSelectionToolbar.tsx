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
    <div className="mb-3 space-y-2">
      {/* Selection-action buttons - free to wrap on their own if the tree
          gets a long "Epics, Features & Stories only"-style label or a
          narrow viewport, WITHOUT ever affecting the Apply row below it. */}
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
      {/* Count + submit get their own dedicated row so the button's
          position is deterministic regardless of how wide the buttons
          above are, or how many digits a large tree's count reaches
          ("567 / 1566 selected" previously dragged the button down onto
          the same wrapped line as the count when this shared a row with
          the selection-action buttons). */}
      <div className="flex items-center justify-between gap-3">
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
