import type { GenerateStage, ImportStage } from "@/lib/types";

const IMPORT_STAGES: ImportStage[] = [
  "queued",
  "authenticating",
  "discovering_fields",
  "fetching_hierarchy",
  "fetching_work_items",
  "downloading_assets",
  "creating_snapshot",
  "completed",
];

const GENERATE_STAGES: GenerateStage[] = [
  "queued",
  "normalizing_content",
  "running_llm_rules",
  "rendering_docx",
  "converting_pdf",
  "verifying_document",
  "completed",
];

function formatStage(stage: string): string {
  return stage
    .split("_")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

export function JobStageList({ jobType, currentStage }: { jobType: "import" | "generate"; currentStage: string }) {
  const stages = jobType === "import" ? IMPORT_STAGES : GENERATE_STAGES;
  const currentIndex = stages.indexOf(currentStage as never);

  return (
    <ol className="relative">
      {stages.map((stage, index) => {
        const state = currentIndex < 0 ? "pending" : index < currentIndex ? "done" : index === currentIndex ? "active" : "pending";
        const isLast = index === stages.length - 1;
        return (
          <li key={stage} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast && (
              <span
                aria-hidden="true"
                className={`absolute left-[5px] top-3 h-full w-px ${state === "done" ? "bg-success" : "bg-line"}`}
              />
            )}
            <span
              className={`relative z-10 mt-0.5 flex h-[11px] w-[11px] shrink-0 items-center justify-center rounded-full ${
                state === "done"
                  ? "bg-success"
                  : state === "active"
                    ? "bg-accent"
                    : "bg-surface-raised ring-1 ring-inset ring-line-strong"
              }`}
            >
              {state === "active" && (
                <span className="absolute h-[11px] w-[11px] animate-ping rounded-full bg-accent opacity-60" />
              )}
            </span>
            <span
              className={`text-sm ${
                state === "pending" ? "text-ink-faint" : state === "active" ? "font-medium text-ink" : "text-ink-muted"
              }`}
            >
              {formatStage(stage)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
