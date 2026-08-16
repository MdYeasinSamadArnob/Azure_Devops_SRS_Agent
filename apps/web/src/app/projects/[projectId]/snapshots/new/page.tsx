import { NewSnapshotSelectionTemplate } from "@/components/templates/NewSnapshotSelectionTemplate";

export default async function NewSnapshotPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ jobId?: string }>;
}) {
  const { projectId } = await params;
  const { jobId } = await searchParams;
  return <NewSnapshotSelectionTemplate projectId={projectId} jobId={jobId ?? null} />;
}
