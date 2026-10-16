import { ExposureLens } from "@/components/exposure/ExposureLens";

export default async function ExposurePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ExposureLens investigationId={id} />;
}
