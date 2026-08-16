import { GenerationHistoryTemplate } from "@/components/templates/GenerationHistoryTemplate";

export default async function GenerationHistoryPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <GenerationHistoryTemplate projectId={projectId} />;
}
