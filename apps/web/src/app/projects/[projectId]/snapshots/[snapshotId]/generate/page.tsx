import { GenerateTemplate } from "@/components/templates/GenerateTemplate";

export default async function GeneratePage({
  params,
}: {
  params: Promise<{ projectId: string; snapshotId: string }>;
}) {
  const { projectId, snapshotId } = await params;
  return <GenerateTemplate projectId={projectId} snapshotId={snapshotId} />;
}
