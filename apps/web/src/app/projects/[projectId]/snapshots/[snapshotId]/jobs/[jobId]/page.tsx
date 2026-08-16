import { JobWatchTemplate } from "@/components/templates/JobWatchTemplate";

export default async function GenerationJobPage({
  params,
}: {
  params: Promise<{ projectId: string; snapshotId: string; jobId: string }>;
}) {
  const { snapshotId, jobId } = await params;
  return <JobWatchTemplate snapshotId={snapshotId} jobId={jobId} />;
}
