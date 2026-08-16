"use client";

import { useJobEventSource } from "@/hooks/useJobEventSource";
import { JobStageList } from "@/components/molecules/JobStageList";
import { Badge } from "@/components/atoms/Badge";
import { Spinner } from "@/components/atoms/Spinner";

export function JobProgress({ jobId, jobType }: { jobId: string; jobType: "import" | "generate" }) {
  const { job } = useJobEventSource(jobId);

  if (!job) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-faint">
        <Spinner /> Connecting to job…
      </div>
    );
  }

  const toneMap = {
    queued: "neutral",
    running: "info",
    completed: "success",
    failed: "error",
    cancelled: "warning",
  } as const;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Badge tone={toneMap[job.status]}>{job.status}</Badge>
        <span className="font-mono text-xs text-ink-faint">{job.progress_percent}%</span>
      </div>
      <JobStageList jobType={jobType} currentStage={job.stage} />
      {job.error_message && (
        <p role="alert" className="rounded-md bg-error/10 px-3 py-2 text-sm text-error">
          {job.error_message}
        </p>
      )}
    </div>
  );
}
