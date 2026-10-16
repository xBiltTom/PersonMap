import { ReconstructionView } from "@/components/reconstruction/ReconstructionView";

export default async function ReconstructionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReconstructionView key={id} investigationId={id} />;
}
