import { Badge } from "@/components/atoms/Badge";

interface ImportSummaryCardProps {
  sourceUrl: string;
  status: string;
  warningCount?: number;
}

const STATUS_TONE = {
  completed: "success",
  sealed: "success",
  failed: "error",
} as const;

export function ImportSummaryCard({ sourceUrl, status, warningCount = 0 }: ImportSummaryCardProps) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-surface-raised px-4 py-3">
      <p className="truncate font-mono text-[13px] text-ink-muted">{sourceUrl}</p>
      <div className="flex shrink-0 items-center gap-2">
        {warningCount > 0 && (
          <Badge tone="warning">
            {warningCount} warning{warningCount === 1 ? "" : "s"}
          </Badge>
        )}
        <Badge tone={STATUS_TONE[status as keyof typeof STATUS_TONE] ?? "info"}>{status}</Badge>
      </div>
    </div>
  );
}
