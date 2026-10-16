"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ApiError, getReconstruction, buildReconstruction } from "../../lib/api";
import type { ReconstructionReport } from "../../lib/types";
import { visibleReconstruction } from "../../lib/reconstructionState";
import { ReconstructionStatus } from "./ReconstructionStatus";
import { ReconstructionSections } from "./ReconstructionSections";
import { ReconstructionAnalysis } from "./ReconstructionAnalysis";
import styles from "./ReconstructionView.module.css";

const ReconstructionGraph = dynamic(() => import("./ReconstructionGraph"), {
  ssr: false, loading: () => <p role="status">Cargando grafo…</p>,
});

export function ReconstructionView({ investigationId }: { investigationId: string }) {
  const [report, setReport] = useState<ReconstructionReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    getReconstruction(investigationId).then(next => {
      if (!cancelled) { setReport(next); setError(null); }
    }).catch((cause: unknown) => {
      if (!cancelled) { setReport(null); setError({ message: cause instanceof Error ? cause.message : "No se pudo cargar la reconstrucción.",
        code: cause instanceof ApiError ? cause.code : undefined }); }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [investigationId]);
  async function build() {
    setBuilding(true); setError(null);
    try { setReport(await buildReconstruction(investigationId)); }
    catch (cause) {
      // A failed refresh must not leave the old snapshot on screen.
      setReport(null);
      setError({ message: cause instanceof Error ? cause.message : "No se pudo reconstruir la huella.",
        code: cause instanceof ApiError ? cause.code : undefined });
    } finally { setBuilding(false); }
  }
  const snapshot = visibleReconstruction(report);
  return <main className={styles.page}>
    <Link className="reconstruction-back" href={`/investigation/${investigationId}/exposure`}>← Exposure Lens</Link>
    <header className="reconstruction-header"><p>FAIR · HUELLA REVISADA</p>
      <h1>Tu huella digital reconstruida</h1>
      <p>Construida únicamente con datos declarados o confirmados y evidencia pública observada.</p>
      <p>Esta es la huella reconstruible a partir de las fuentes observadas.</p>
    </header>
    {loading ? <p role="status">Cargando reconstrucción…</p> : <>
      <ReconstructionStatus report={report} error={error} building={building} investigationId={investigationId} onBuild={() => void build()} />
      {snapshot && <>
        <section className="reconstruction-stats" aria-label="Resumen de la huella">
          {[[snapshot.counts.account || 0, "cuentas atribuidas"], [snapshot.counts.alias || 0, "aliases"],
            [snapshot.counts.public_identifiers || 0, "identificadores públicos"],
            [(snapshot.counts.document || 0) + (snapshot.counts.publication || 0), "documentos"],
            [(snapshot.counts.post || 0) + (snapshot.counts.repository || 0), "publicaciones y repos"],
            [snapshot.counts.exposure || 0, "señales de exposición"]].map(([count, label]) =>
            <div key={label}><strong>{count}</strong><span>{label}</span></div>)}
        </section>
        <ReconstructionAnalysis key={`analysis:${snapshot.input_hash}`} snapshot={snapshot} />
        <ReconstructionGraph key={`graph:${snapshot.input_hash}`} snapshot={snapshot} />
        <ReconstructionSections snapshot={snapshot} />
      </>}
    </>}
  </main>;
}
