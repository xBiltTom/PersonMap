import { VerificationGate } from "@/components/review/VerificationGate";

export default async function ReviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <VerificationGate investigationId={id} />;
}
