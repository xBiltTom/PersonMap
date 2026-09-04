"use client";

import { use, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { InvestigationData } from "@/lib/types";
import { getInvestigation } from "@/lib/api";
import { DigitalMapGraph } from "@/components/graph/DigitalMapGraph";
import { IdentityClustersView } from "@/components/identity/IdentityClustersView";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { DiscoveryTimeline } from "@/components/timeline/DiscoveryTimeline";
import { LiveConsole } from "@/components/console/LiveConsole";
import { ReportView } from "@/components/report/ReportView";
import {
  ArrowLeft,
  Network,
  ShieldCheck,
  Table,
  Clock,
  Terminal,
  FileText,
  RefreshCw,
  Download,
  AlertCircle,
} from "lucide-react";

export default function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const id = resolvedParams.id;

  const [investigation, setInvestigation] = useState<InvestigationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    "graph" | "identity" | "findings" | "timeline" | "console" | "report"
  >("graph");

  const loadData = useCallback(async () => {
    try {
      const data = await getInvestigation(id);
      setInvestigation(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "No se pudo cargar la investigación");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadData();
    // Poll every 4 seconds if still running
    const interval = setInterval(() => {
      if (investigation?.status === "running" || investigation?.status === "pending") {
        loadData();
      }
    }, 4000);

    return () => clearInterval(interval);
  }, [id, loadData, investigation?.status]);

  const handleExportJson = () => {
    if (!investigation) return;
    const blob = new Blob([JSON.stringify(investigation, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `person-map-${investigation.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="py-24 text-center">
        <div className="w-6 h-6 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mx-auto mb-3" />
        <p className="text-xs font-mono text-slate-400">Recuperando expediente forense...</p>
      </div>
    );
  }

  if (error || !investigation) {
    return (
      <div className="panel-card p-8 text-center max-w-md mx-auto my-12">
        <AlertCircle className="w-8 h-8 text-rose-400 mx-auto mb-2" />
        <h3 className="text-sm font-semibold text-slate-200">Error al cargar</h3>
        <p className="text-xs text-slate-400 mt-1">{error || "Expediente no encontrado"}</p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-1.5 text-xs font-mono text-sky-400 hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Volver al panel principal
        </Link>
      </div>
    );
  }

  const targetName =
    investigation.target?.full_name ||
    investigation.target?.username ||
    investigation.target?.email ||
    "Objetivo";

  const isRunning = investigation.status === "running" || investigation.status === "pending";

  const tabs = [
    { id: "graph", label: "Mapa Digital", icon: Network },
    { id: "identity", label: "Reconstrucción de Identidad", icon: ShieldCheck },
    { id: "findings", label: `Hallazgos (${investigation.entities?.length || 0})`, icon: Table },
    { id: "timeline", label: "Línea de Tiempo", icon: Clock },
    { id: "console", label: "Consola en Vivo", icon: Terminal },
    { id: "report", label: "Informe de Concientización", icon: FileText },
  ];

  return (
    <div className="space-y-6">
      {/* Dossier Header Bar */}
      <div className="panel-card p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link
                href="/"
                className="text-xs font-mono text-slate-500 hover:text-sky-400 flex items-center gap-1 transition-colors"
              >
                <ArrowLeft className="w-3 h-3" /> Investigaciones
              </Link>
              <span className="text-slate-700">/</span>
              <span className="text-xs font-mono text-slate-400 uppercase">
                ID: {investigation.id.slice(0, 8)}
              </span>
            </div>

            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold text-slate-100 font-sans">{targetName}</h1>
              {investigation.target?.university && (
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-[#1c2738] text-sky-300 border border-[#2b3d58]">
                  {investigation.target.university}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 mt-2 text-xs font-mono text-slate-400">
              {investigation.target?.email && <span>📧 {investigation.target.email}</span>}
              {investigation.target?.username && <span>👤 @{investigation.target.username}</span>}
              {investigation.target?.dni && <span>🪪 DNI: {investigation.target.dni}</span>}
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0 print:hidden">
            <div className="text-right">
              <div className="text-xs font-mono font-bold text-slate-200">
                Score: {investigation.risk_score}/100
              </div>
              <span
                className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase font-semibold ${
                  isRunning
                    ? "bg-sky-500/10 text-sky-400 border border-sky-500/20"
                    : investigation.status === "completed"
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                }`}
              >
                {investigation.status}
              </span>
            </div>

            <button
              onClick={loadData}
              title="Refrescar expediente"
              className="p-2 rounded bg-[#182334] hover:bg-[#223148] text-slate-300 border border-[#2b3a52] transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isRunning ? "animate-spin text-sky-400" : ""}`} />
            </button>

            <button
              onClick={handleExportJson}
              title="Descargar expediente en formato JSON"
              className="flex items-center gap-1.5 px-3 py-2 rounded bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-sky-400" />
              <span>Exportar</span>
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div
          role="tablist"
          aria-label="Secciones del expediente"
          className="flex items-center gap-1 overflow-x-auto border-t border-[#1e293b] mt-5 pt-3 print:hidden"
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-md text-xs font-mono transition-all whitespace-nowrap cursor-pointer border ${
                  isActive
                    ? "bg-sky-500/20 text-sky-300 border-sky-500/30 font-semibold"
                    : "text-slate-300 hover:text-slate-100 hover:bg-[#151e2c] border-transparent"
                }`}
              >
                <Icon className="w-3.5 h-3.5" aria-hidden="true" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content Panels */}
      <div>
        {activeTab === "graph" && (
          <DigitalMapGraph investigationId={investigation.id} />
        )}

        {activeTab === "identity" && (
          <IdentityClustersView
            investigationId={investigation.id}
            clusters={investigation.identity_clusters || []}
            onEntityUpdated={loadData}
          />
        )}

        {activeTab === "findings" && (
          <FindingsTable entities={investigation.entities || []} />
        )}

        {activeTab === "timeline" && (
          <DiscoveryTimeline entities={investigation.entities || []} />
        )}

        {activeTab === "console" && (
          <LiveConsole
            investigationId={investigation.id}
            isFinished={investigation.status === "completed" || investigation.status === "failed"}
          />
        )}

        {activeTab === "report" && (
          <ReportView investigation={investigation} />
        )}
      </div>
    </div>
  );
}
