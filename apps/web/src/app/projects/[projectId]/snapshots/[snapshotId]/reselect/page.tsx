import { ReselectSnapshotTemplate } from "@/components/templates/ReselectSnapshotTemplate";

export default async function ReselectSnapshotPage({
  params,
}: {
  params: Promise<{ projectId: string; snapshotId: string }>;
}) {
  const { projectId, snapshotId } = await params;
  return <ReselectSnapshotTemplate projectId={projectId} snapshotId={snapshotId} />;
}
