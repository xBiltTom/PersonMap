"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ApiError, getReconstruction, buildReconstruction, getReconstructionProviders,
  getMcpReconstruction, requestMcpReconstruction, cancelMcpReconstruction } from "../../lib/api";
import type { ReconstructionReport, ReconstructionProviders, ReconstructionRequest } from "../../lib/types";
import { visibleReconstruction } from "../../lib/reconstructionState";
import { ReconstructionStatus } from "./ReconstructionStatus";
import { ReconstructionSections } from "./ReconstructionSections";
import { ReconstructionAnalysis } from "./ReconstructionAnalysis";
import { ReconstructionProviderChoice, McpReconstructionPanel, mcpRequestActive, type ReconstructionMode } from "./ReconstructionWorkflow";
import styles from "./ReconstructionView.module.css";

const ReconstructionGraph = dynamic(() => import("./ReconstructionGraph"), {
  ssr: false, loading: () => <p role="status">Cargando grafo…</p>,
});
const describeError = (cause: unknown) => ({ message: cause instanceof Error ? cause.message : "No se pudo cargar la reconstrucción.",
  code: cause instanceof ApiError ? cause.code : undefined });

export function ReconstructionView({ investigationId }: { investigationId: string }) {
  const [report, setReport] = useState<ReconstructionReport | null>(null);
  const [providers, setProviders] = useState<ReconstructionProviders | null>(null);
  const [mcpRequest, setMcpRequest] = useState<ReconstructionRequest | null>(null);
  const [mode, setMode] = useState<ReconstructionMode>("integrated");
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<{ message: string; code?: string } | null>(null);
  const [mcpError, setMcpError] = useState<{ message: string; code?: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([getReconstruction(investigationId), getReconstructionProviders(investigationId),
      getMcpReconstruction(investigationId)]).then(([integrated, configuration, external]) => {
      if (cancelled) return;
      if (integrated.status === "fulfilled") { setReport(integrated.value); setError(null); }
      else { setReport(null); setError(describeError(integrated.reason)); }
      if (configuration.status === "fulfilled") setProviders(configuration.value);
      else { setProviders(null); setError(describeError(configuration.reason)); }
      if (external.status === "fulfilled") { setMcpRequest(external.value); setMcpError(null); }
      else { setMcpRequest(null); setMcpError(describeError(external.reason)); }
      let preferred: ReconstructionMode = "integrated";
      try { if (localStorage.getItem(`reconstruction-mode:${investigationId}`) === "mcp") preferred = "mcp"; } catch { /* Storage can be disabled. */ }
      if (external.status === "fulfilled" && mcpRequestActive(external.value)) preferred = "mcp";
      setMode(preferred); setLoading(false);
    });
    return () => { cancelled = true; };
  }, [investigationId]);

  const waiting = mcpRequestActive(mcpRequest);
  const requestId = mcpRequest?.id;
  useEffect(() => {
    if (!waiting || !requestId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getMcpReconstruction(investigationId);
        if (!cancelled) { setMcpRequest(next); setMcpError(null); }
      } catch (cause) {
        if (!cancelled) setMcpError(describeError(cause));
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 3000);
      }
    }
    timer = setTimeout(() => void poll(), 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [investigationId, requestId, waiting]);

  function changeMode(next: ReconstructionMode) {
    setMode(next);
    try { localStorage.setItem(`reconstruction-mode:${investigationId}`, next); } catch { /* Selection still works without storage. */ }
  }
  async function build() {
    setBuilding(true); setError(null);
    try { setReport(await buildReconstruction(investigationId)); }
    catch (cause) { setReport(null); setError(describeError(cause)); }
    finally { setBuilding(false); }
  }
  async function startMcp() {
    setBuilding(true); setMcpError(null);
    try { setMcpRequest(await requestMcpReconstruction(investigationId)); }
    catch (cause) { setMcpError(describeError(cause)); }
    finally { setBuilding(false); }
  }
  async function cancelMcp() {
    if (!mcpRequest) return;
    setBuilding(true); setMcpError(null);
    try { setMcpRequest(await cancelMcpReconstruction(investigationId, mcpRequest.id)); }
    catch (cause) { setMcpError(describeError(cause)); }
    finally { setBuilding(false); }
  }
  const snapshot = visibleReconstruction(mode === "mcp" ? mcpRequest?.result ?? null : report);
  return <main className={styles.page}>
    <Link className="reconstruction-back" href={`/investigation/${investigationId}/exposure`}>← Exposure Lens</Link>
    <header className="reconstruction-header"><p>FAIR · HUELLA REVISADA</p>
      <h1>Tu huella digital reconstruida</h1>
      <p>Construida con datos declarados o confirmados y evidencia pública observada.</p>
    </header>
    {loading ? <p role="status">Cargando reconstrucción…</p> : <>
      <ReconstructionProviderChoice mode={mode} providers={providers} disabled={building} onChange={changeMode} />
      {mode === "integrated" ? <>
        {providers && !providers.integrated.enabled && <aside className="reconstruction-notice" role="status">{providers.integrated.reason}</aside>}
        <ReconstructionStatus report={report} error={error} building={building} investigationId={investigationId}
          buildDisabled={providers ? !providers.integrated.enabled : true} onBuild={() => void build()} />
      </> : <McpReconstructionPanel key={mcpRequest?.id || investigationId} request={mcpRequest}
        enabled={providers?.mcp.enabled ?? false} reason={providers?.mcp.reason} busy={building} error={mcpError}
        onRequest={() => void startMcp()} onCancel={() => void cancelMcp()} />}
      {snapshot && <>
        <p className="reconstruction-result-source">{snapshot.analysis_provider === "mcp"
          ? `Análisis recibido por MCP${mcpRequest?.client ? ` · ${mcpRequest.client}` : ""}`
          : `IA integrada${snapshot.narrative_model ? ` · ${snapshot.narrative_model}` : ""}`}</p>
        <section className="reconstruction-stats" aria-label="Resumen de la huella">
          {[[snapshot.counts.account || 0, "cuentas atribuidas"], [snapshot.counts.alias || 0, "aliases"],
            [snapshot.counts.public_identifiers || 0, "identificadores públicos"],
            [(snapshot.counts.document || 0) + (snapshot.counts.publication || 0), "documentos"],
            [(snapshot.counts.post || 0) + (snapshot.counts.repository || 0), "publicaciones y repos"],
            [snapshot.counts.exposure || 0, "señales de exposición"]].map(([count, label]) =>
            <div key={label}><strong>{count}</strong><span>{label}</span></div>)}
        </section>
        <ReconstructionAnalysis key={`analysis:${snapshot.input_hash}:${snapshot.generated_at}`} snapshot={snapshot} />
        <ReconstructionGraph key={`graph:${snapshot.input_hash}:${snapshot.generated_at}`} snapshot={snapshot} />
        <ReconstructionSections snapshot={snapshot} />
      </>}
    </>}
  </main>;
}
