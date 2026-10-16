import type { ReconstructionReport } from "../../lib/types";
import { reconstructionNextStep, visibleReconstruction } from "../../lib/reconstructionState.ts";

export function ReconstructionStatus({ report, error, building, investigationId, onBuild }: {
  report: ReconstructionReport | null; error: { message: string; code?: string } | null;
  building: boolean; investigationId: string; onBuild: () => void;
}) {
  const next = reconstructionNextStep(error?.code);
  const snapshot = visibleReconstruction(report);
  return <>
    {error && <aside role="alert" className="reconstruction-notice"><strong>{error.message}</strong>
      {next && <a href={`/investigation/${investigationId}/${next.path}`}>{next.label} →</a>}
    </aside>}
    {!next && <section className="reconstruction-actions" aria-label="Estado de reconstrucción">
      <p>{report?.stale ? "La evidencia cambió. Reconstruye la huella actual." : !snapshot ? "La huella está lista para reconstruir." : "Huella actual de las fuentes observadas."}</p>
      <button type="button" onClick={onBuild} disabled={building}>
        {building ? "Construyendo…" : snapshot ? "Actualizar reconstrucción" : "Construir reconstrucción"}</button>
    </section>}
  </>;
}
