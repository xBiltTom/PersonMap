"use client";

import { use, useEffect, useState, useCallback, useMemo, useRef } from "react";
import Link from "next/link";
import { GraphEdge, GraphNode, GraphResponse, InvestigationData, MaigretReportFormat } from "@/lib/types";
import { getInvestigation, getInvestigationGraph, getGraphmlUrl, getMaigretCapabilities, downloadMaigretReport } from "@/lib/api";
import { targetDisplayName } from "@/lib/targetLabel";
import { ENGINE_META, resolveEngine } from "@/lib/engines";
import { DigitalMapGraph } from "@/components/graph/DigitalMapGraph";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { DiscoveryTimeline } from "@/components/timeline/DiscoveryTimeline";
import { LiveConsole } from "@/components/console/LiveConsole";
import { InvestigationProgress } from "@/components/console/InvestigationProgress";
import { useInvestigationStream } from "@/lib/useInvestigationStream";
import { ReportView } from "@/components/report/ReportView";
import { AnalysisNotebook } from "@/components/investigation/AnalysisNotebook";
import { EntityInspector, RelationshipInspector } from "@/components/graph/EntityInspector";
import { entityToGraphNode } from "@/lib/entityInspector";
import { getFriendlyRelationLabel, isProvenanceEdge } from "@/lib/graphSemantics";
import { useWorkstation } from "@/context/WorkstationContext";
import {
  ArrowLeft,
  Network,
  Table,
  Clock,
  Terminal,
  RefreshCw,
  Download,
  AlertCircle,
  CheckCircle2,
  XCircle,
  ChevronDown,
  Printer,
  FileDown,
  Copy,
  Check,
  Maximize2,
  ChevronUp,
  ShieldCheck,
  Mail,
  AtSign,
  Fingerprint,
  CalendarDays,
  MoreHorizontal,
} from "lucide-react";

type WorkspaceSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string };

// Acción temporalmente oculta para la muestra.
const SHOW_EXPORT_ACTIONS = false;

function formatDate(value?: string): string {
  if (!value) return "Fecha no registrada";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-PE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function InvestigationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const id = resolvedParams.id;

  const { setActiveInvestigation, activeTab, setActiveTab } = useWorkstation();

  const [investigation, setInvestigation] = useState<InvestigationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [mapFocusNodeId, setMapFocusNodeId] = useState<string | null>(null);
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [maigretFormats, setMaigretFormats] = useState<MaigretReportFormat[]>([]);
  const [exportingMaigret, setExportingMaigret] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const [copiedId, setCopiedId] = useState(false);
  const [isMapCollapsed, setIsMapCollapsed] = useState(false);
  const [workspaceSelection, setWorkspaceSelection] = useState<WorkspaceSelection | null>(null);

  const exportMenuRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const mapSectionRef = useRef<HTMLDivElement>(null);
  const loadMaigretExports = SHOW_EXPORT_ACTIONS && Boolean(investigation && investigation.metrics.acquisition_mode !== "fair");
  useEffect(() => {
    if (!loadMaigretExports) return;
    let cancelled = false;
    getMaigretCapabilities().then((capabilities) => { if (!cancelled) setMaigretFormats(capabilities.report_formats); }).catch(() => {});
    return () => { cancelled = true; };
  }, [loadMaigretExports]);

  const loadData = useCallback(async () => {
    try {
      const data = await getInvestigation(id);
      // Concurrent tools can finish together; a slower older response must not undo newer evidence.
      setInvestigation((current) => current?.id === data.id && data.execution_mode === "external"
        && (current.revision ?? 0) > (data.revision ?? 0) ? current : data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo cargar la investigación");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void loadData();
    }, 0);

    const interval = setInterval(() => {
      if (investigation?.status === "running" || investigation?.status === "pending") {
        loadData();
      }
    }, 4000);

    return () => {
      clearTimeout(initialLoad);
      clearInterval(interval);
    };
  }, [id, loadData, investigation?.status]);

  // Sync active investigation with WorkstationContext
  useEffect(() => {
    if (investigation) {
      const targetName = targetDisplayName(investigation.target);

      setActiveInvestigation({
        id: investigation.id,
        code: `PM-${investigation.id.slice(0, 4).toUpperCase()}`,
        targetName,
        status: investigation.status,
        findingsCount: investigation.entities?.length ?? 0,
        strategy: investigation.strategy,
        created_at: investigation.created_at,
      });
    }
  }, [investigation, setActiveInvestigation]);

  // Load graph data once investigation is retrieved
  useEffect(() => {
    if (!investigation?.id) return;
    let cancelled = false;
    const requestTimer = window.setTimeout(() => {
      void getInvestigationGraph(id)
        .then((data) => {
          if (!cancelled) setGraph(data);
        })
        .catch(() => {
          if (!cancelled) setGraph(null);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(requestTimer);
    };
  }, [id, investigation?.completed_at, investigation?.entities?.length, investigation?.id, investigation?.status, investigation?.revision]);

  // Close menus on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setIsExportOpen(false);
      }
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setIsMoreMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleViewInMap = useCallback((entityId: string) => {
    const nodeId = `ent-${entityId}`;
    setMapFocusNodeId(nodeId);
    // Esta acción navega, no inspecciona. El detalle se abre exclusivamente
    // desde el icono de ojo o al seleccionar una entidad en el lienzo.
    setWorkspaceSelection(null);
    setActiveTab("graph");
    // If map was collapsed, expand it
    setIsMapCollapsed(false);

    window.requestAnimationFrame(() => {
      mapSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [setActiveTab]);

  const handleViewTrace = useCallback(() => {
    // La consola no duplica el inspector de una ejecución: dirige al
    // explorador de trazabilidad, que es la fuente de verdad de ese detalle.
    setActiveTab("timeline");
  }, [setActiveTab]);

  const workspaceNodes = useMemo<GraphNode[]>(
    () => graph?.nodes ?? (investigation?.entities ?? []).map(entityToGraphNode),
    [graph, investigation?.entities]
  );
  const workspaceEdges = useMemo<GraphEdge[]>(() => graph?.edges ?? [], [graph]);
  const selectedWorkspaceNode = workspaceSelection?.kind === "node"
    ? workspaceNodes.find((node) => node.id === workspaceSelection.id) ?? null
    : null;
  const selectedWorkspaceEdge = workspaceSelection?.kind === "edge"
    ? workspaceEdges.find((edge) => edge.id === workspaceSelection.id) ?? null
    : null;

  const inspectNode = useCallback((nodeId: string) => {
    setWorkspaceSelection({ kind: "node", id: nodeId });
  }, []);
  const inspectEdge = useCallback((edgeId: string) => {
    setWorkspaceSelection({ kind: "edge", id: edgeId });
  }, []);
  const selectInspectorNode = useCallback((nodeId: string) => {
    setMapFocusNodeId(nodeId);
    setWorkspaceSelection({ kind: "node", id: nodeId });
  }, []);
  const closeWorkspaceInspector = useCallback(() => {
    setWorkspaceSelection(null);
  }, []);

  useEffect(() => {
    if (!workspaceSelection) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeWorkspaceInspector();
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [closeWorkspaceInspector, workspaceSelection]);

  const wasRunning = investigation?.status === "running" || investigation?.status === "pending";
  const handleStreamFinished = useCallback(() => {
    if (wasRunning) loadData();
  }, [wasRunning, loadData]);
  const stream = useInvestigationStream(id, handleStreamFinished, loadData);

  const handleExportJson = () => {
    if (!investigation) return;
    const blob = new Blob([JSON.stringify(investigation, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `person-map-${investigation.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setIsExportOpen(false);
  };

  const handleMaigretExport = async (format: MaigretReportFormat) => {
    if (!investigation) return;
    setExportingMaigret(format.toUpperCase());
    setExportError(null);
    setIsExportOpen(false);
    try {
      const blob = await downloadMaigretReport(investigation.id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const extensions: Partial<Record<MaigretReportFormat, string>> = { markdown: "md", ndjson: "jsonl", graph: "html", neo4j: "cypher" };
      const extension = extensions[format] || format;
      anchor.href = url;
      anchor.download = `maigret-${format}-${investigation.id}.${extension}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "No se pudo exportar el informe Maigret");
    } finally {
      setExportingMaigret(null);
    }
  };

  const handleCopyId = () => {
    if (!investigation) return;
    navigator.clipboard.writeText(investigation.id).then(() => {
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
      setIsMoreMenuOpen(false);
    });
  };

  // Metric computations (Factual and semantically distinct)
  const findingsCount = investigation?.entities?.length ?? 0;

  // Documented evidence relationships (excluding provenance helper links)
  const relationsCount = useMemo(() => {
    if (graph?.edges?.length) {
      return graph.edges.filter((e) => !isProvenanceEdge(e)).length;
    }
    return 0;
  }, [graph]);

  // Distinct tool sources that provided data
  const sourcesCount = useMemo(() => {
    const sources = new Set((investigation?.entities || []).map((e) => e.source_tool));
    return sources.size;
  }, [investigation?.entities]);

  if (loading) {
    return (
      <div className="py-32 text-center select-none font-mono">
        <div className="w-7 h-7 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mx-auto mb-3" />
        <p className="text-xs text-slate-400">Recuperando expediente forense...</p>
        <p className="text-[10px] text-slate-600 mt-1">Conectando con el motor OSINT</p>
      </div>
    );
  }

  if (error || !investigation) {
    return (
      <div className="panel-card p-8 text-center max-w-md mx-auto my-16 border border-rose-500/30">
        <AlertCircle className="w-8 h-8 text-rose-400 mx-auto mb-2" />
        <h3 className="text-sm font-semibold text-slate-200">Error al cargar expediente</h3>
        <p className="text-xs text-slate-400 mt-1">{error || "Expediente no encontrado en la base de datos"}</p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#142032] border border-[#213550] text-xs font-mono text-sky-300 hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Volver al centro de mando
        </Link>
      </div>
    );
  }

  const targetName = targetDisplayName(investigation.target);

  const code = `PM-${investigation.id.slice(0, 4).toUpperCase()}`;
  const isRunning = investigation.status === "running" || investigation.status === "pending";
  const isCompleted = investigation.status === "completed";
  const isFailed = investigation.status === "failed";
  const hasMaigretEvidence = (investigation.entities ?? []).some((entity) => entity.metadata_info?.search_engine === "maigret");
  const engineMeta = ENGINE_META[resolveEngine(investigation.strategy, investigation.metrics)];

  const lowerTabs = [
    { id: "findings", label: `Hallazgos (${findingsCount})`, icon: Table },
    { id: "timeline", label: "Trazabilidad", icon: Clock },
    // { id: "analysis", label: `Análisis (${investigation.analysis_notes?.length ?? 0})`, icon: BookOpen },
    { id: "console", label: "Consola", icon: Terminal },
  ];

  return (
    <div className="space-y-4 max-w-7xl mx-auto">
      {/* Resumen del expediente */}
      <section aria-label="Resumen de la auditoría" className="overflow-visible border border-[#1c2c40] bg-[#0d1420] shadow-[0_18px_48px_rgba(0,0,0,0.22)]">
        <div className="grid gap-4 p-4 sm:p-5 2xl:grid-cols-[minmax(0,1fr)_300px_300px] 2xl:items-center 2xl:gap-5">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 title={targetName} className="max-w-full truncate text-xl font-semibold leading-tight tracking-[-0.035em] text-slate-100 sm:text-2xl">
                {targetName}
              </h1>
              {investigation.target?.university && (
                <span className="inline-flex shrink-0 items-center border border-[#244362] bg-[#101d2c] px-2 py-1 text-[10px] font-medium text-sky-200">
                  {investigation.target.university}
                </span>
              )}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px] text-slate-400">
              <span className="font-mono font-medium text-slate-300">{code}</span>
              <span aria-hidden="true" className="text-slate-700">/</span>
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
                {formatDate(investigation.created_at)}
              </span>
              <span className={`inline-flex items-center gap-1.5 border px-2 py-1 text-[10px] font-medium ${engineMeta.badge}`}>
                <span className="h-1.5 w-1.5 bg-current" aria-hidden="true" />
                {engineMeta.label}
              </span>
            </div>

            <div role="group" aria-label="Identificadores del objetivo" className="mt-3 flex flex-wrap gap-2">
              {investigation.target?.email && (
                <span className="inline-flex min-w-0 max-w-full items-center gap-2 border border-[#1d2c40] bg-[#090f18] px-2.5 py-1.5 text-[11px] text-slate-300" title={investigation.target.email}>
                  <Mail className="h-3.5 w-3.5 shrink-0 text-sky-400" aria-hidden="true" />
                  <span className="max-w-[18rem] truncate">{investigation.target.email}</span>
                </span>
              )}
              {investigation.target?.username && (
                <span className="inline-flex min-w-0 max-w-full items-center gap-2 border border-[#1d2c40] bg-[#090f18] px-2.5 py-1.5 text-[11px] text-slate-300">
                  <AtSign className="h-3.5 w-3.5 shrink-0 text-sky-400" aria-hidden="true" />
                  <span className="max-w-[18rem] truncate">{investigation.target.username}</span>
                </span>
              )}
              {investigation.target?.dni && (
                <span className="inline-flex items-center gap-2 border border-[#1d2c40] bg-[#090f18] px-2.5 py-1.5 text-[11px] text-slate-300">
                  <Fingerprint className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                  DNI {investigation.target.dni}
                </span>
              )}
            </div>
          </div>

          <div className="contents">
            <div className="grid min-w-0 grid-cols-3 gap-px border border-[#22344d] bg-[#22344d]" role="group" aria-label="Métricas de la auditoría">
              <div className="min-w-0 bg-[#0a111b] px-3 py-2.5 sm:px-4">
                <div className="text-lg font-semibold leading-none text-sky-300 sm:text-xl">{findingsCount}</div>
                <div className="mt-1.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">Hallazgos</div>
              </div>
              <div className="min-w-0 bg-[#0a111b] px-3 py-2.5 sm:px-4">
                <div className="text-lg font-semibold leading-none text-slate-100 sm:text-xl">{relationsCount}</div>
                <div className="mt-1.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">Relaciones</div>
              </div>
              <div className="min-w-0 bg-[#0a111b] px-3 py-2.5 sm:px-4">
                <div className="text-lg font-semibold leading-none text-slate-100 sm:text-xl">{sourcesCount}</div>
                <div className="mt-1.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">Fuentes</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-[#1b2c41] pt-4 2xl:justify-end 2xl:border-l 2xl:border-t-0 2xl:pl-5 2xl:pt-0">
              <span
                role="status"
                className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 border px-3 text-[11px] font-medium ${
                  isCompleted
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : isRunning
                    ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
                    : isFailed
                    ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                    : "border-amber-500/30 bg-amber-500/10 text-amber-300"
                }`}
              >
                {isCompleted ? (
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                ) : isRunning ? (
                  <Clock className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : investigation.status === "paused" ? (
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                <span>
                  {isCompleted
                    ? "Completado"
                    : isRunning
                    ? "En análisis"
                    : isFailed
                    ? "Fallido"
                    : investigation.status === "paused"
                    ? "Pausado"
                    : investigation.status}
                </span>
              </span>

              {investigation.metrics.acquisition_mode === "fair" && isCompleted && (
                <Link
                  href={`/investigation/${investigation.id}/review`}
                  className="inline-flex min-h-9 items-center gap-1.5 border border-[#eee99a] bg-[#d9d47a] px-3 text-[11px] font-semibold text-[#191b12] transition-colors hover:bg-[#e8e38a]"
                >
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{(investigation.metrics.verification_gate as { status?: string } | undefined)?.status === "complete"
                    ? "Abrir revisión"
                    : "Revisar descubrimientos"}</span>
                </Link>
              )}

              {SHOW_EXPORT_ACTIONS ? <div className="relative shrink-0" ref={exportMenuRef}>
                <button
                  type="button"
                  aria-expanded={isExportOpen}
                  disabled={Boolean(exportingMaigret)}
                  onClick={() => setIsExportOpen((prev) => !prev)}
                  className="flex min-h-9 items-center gap-1.5 border border-[#29405c] bg-[#101b2a] px-3 text-[11px] text-slate-200 transition-colors hover:border-sky-500/50 hover:bg-[#162438] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Download className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                  <span>{exportingMaigret ? `Generando ${exportingMaigret}…` : "Exportar informe"}</span>
                  <ChevronDown className="h-3 w-3 text-slate-400" aria-hidden="true" />
                </button>

                {isExportOpen && (
                  <div className="absolute right-0 top-10 z-50 max-h-[65vh] w-60 overflow-y-auto border border-[#29405c] bg-[#0c131f] p-1 shadow-2xl animate-fade-in font-mono text-xs">
                    <button type="button" onClick={handleExportJson} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                      <Download className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                      <span>Descargar JSON</span>
                    </button>
                    <button type="button" onClick={() => { window.print(); setIsExportOpen(false); }} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                      <Printer className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                      <span>Imprimir / PDF forense</span>
                    </button>
                    <button type="button" onClick={() => { window.open(getGraphmlUrl(investigation.id), "_blank"); setIsExportOpen(false); }} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                      <FileDown className="h-3.5 w-3.5 text-purple-400" aria-hidden="true" />
                      <span>Descargar GraphML</span>
                    </button>
                    {hasMaigretEvidence && maigretFormats.length > 0 && <div className="mt-1 border-t border-[#22344d] pt-2">
                      <p className="px-2.5 pb-1 text-[10px] text-slate-500">Maigret · detecciones y datos</p>
                      {maigretFormats.map((format) => <button key={format} type="button" onClick={() => void handleMaigretExport(format)} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                        <FileDown className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                        <span>{format === "graph" ? "Grafo de enlaces (HTML)" : format === "neo4j" ? "Neo4j (Cypher)" : format.toUpperCase()}</span>
                      </button>)}
                    </div>}
                  </div>
                )}
                {exportError && <p role="alert" className="mt-2 max-w-60 text-xs text-rose-300">{exportError}</p>}
              </div> : null}

              <div className="relative shrink-0" ref={moreMenuRef}>
                <button
                  type="button"
                  aria-label="Más opciones"
                  aria-expanded={isMoreMenuOpen}
                  onClick={() => setIsMoreMenuOpen((prev) => !prev)}
                  className="inline-flex h-9 w-9 items-center justify-center border border-[#1b2a3e] bg-[#0e1624] text-slate-400 transition-colors hover:border-[#314966] hover:bg-[#162438] hover:text-slate-100"
                  title="Más opciones"
                >
                  <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                </button>

                {isMoreMenuOpen && (
                  <div className="absolute right-0 top-10 z-50 w-48 border border-[#29405c] bg-[#0c131f] p-1 shadow-2xl animate-fade-in font-mono text-xs">
                    <button type="button" onClick={handleCopyId} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                      {copiedId ? (
                        <Check className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                      ) : (
                        <Copy className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
                      )}
                      <span>{copiedId ? "ID copiado" : "Copiar ID"}</span>
                    </button>
                    <button type="button" onClick={() => { loadData(); setIsMoreMenuOpen(false); }} className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-slate-300 transition-colors hover:bg-[#162234] hover:text-white">
                      <RefreshCw className="h-3.5 w-3.5 text-sky-400" aria-hidden="true" />
                      <span>Recargar datos</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {isRunning && (
        <InvestigationProgress
          stream={stream}
          startedAt={investigation.created_at}
          onOpenConsole={() => setActiveTab("console")}
        />
      )}

      {/* 2. Vista principal: Informe o Workspace */}
      {activeTab === "report" ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setActiveTab("findings")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#162234] bg-[#0d1420] text-xs font-mono text-slate-300 hover:text-sky-300 hover:border-sky-500/40 transition-colors cursor-pointer"
            >
              <ArrowLeft className="w-3.5 h-3.5 text-sky-400" />
              <span>Volver al Workspace</span>
            </button>
          </div>
          <ReportView investigation={investigation} />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Upper Card: Mapa Digital (Adaptive height + collapsible for 1366x768) */}
          <div
            ref={mapSectionRef}
            className="panel-card scroll-mt-20 overflow-hidden border border-[#162234] bg-[#0d1420] shadow-xl"
          >
            <div className="px-4 py-3 border-b border-[#162234] flex items-center justify-between gap-3 bg-[#090f18]">
              <div className="flex items-center gap-2.5">
                <Network className="w-4 h-4 text-sky-400 shrink-0" />
                <div>
                  <h2 className="text-xs font-mono font-semibold text-slate-200">
                    Mapa digital
                  </h2>
                  <p className="text-[10px] font-mono text-slate-500 hidden sm:block">
                    Visualiza las entidades y sus relaciones documentadas.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsMapCollapsed((prev) => !prev)}
                  className="flex items-center gap-1 px-2.5 py-1 rounded bg-[#101928] hover:bg-[#162438] text-[10px] font-mono text-slate-300 border border-[#1d2c42] transition-colors cursor-pointer"
                  title={isMapCollapsed ? "Expandir lienzo de mapa" : "Colapsar mapa para priorizar tabla"}
                >
                  {isMapCollapsed ? (
                    <>
                      <Maximize2 className="w-3 h-3 text-sky-400" />
                      <span>Expandir mapa</span>
                    </>
                  ) : (
                    <>
                      <ChevronUp className="w-3 h-3 text-slate-400" />
                      <span>Colapsar</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {!isMapCollapsed && (
              <div className="w-full relative transition-all duration-200">
                <DigitalMapGraph
                  investigationId={investigation.id}
                  refreshKey={`${investigation.status}:${investigation.completed_at ?? ""}`}
                  graphData={graph}
                  focusNodeId={mapFocusNodeId}
                  inspectedNodeId={workspaceSelection?.kind === "node" ? workspaceSelection.id : null}
                  inspectedEdgeId={workspaceSelection?.kind === "edge" ? workspaceSelection.id : null}
                  onNodeInspect={inspectNode}
                  onEdgeInspect={inspectEdge}
                  onInspectionClear={closeWorkspaceInspector}
                />
              </div>
            )}
          </div>

          {/* Lower Card: Workspace Multivista (Tabs + Findings/Timeline/Console) */}
          <div className="panel-card overflow-hidden border border-[#162234] bg-[#0d1420] shadow-xl">
            {/* Workspace Subtabs */}
            <div
              role="tablist"
              aria-label="Vistas del workspace"
              className="px-4 py-2 border-b border-[#162234] flex items-center gap-1.5 overflow-x-auto bg-[#090f18] select-none"
            >
              {lowerTabs.map((tab) => {
                const Icon = tab.icon;
                const isTabActive =
                  activeTab === tab.id || (activeTab === "graph" && tab.id === "findings");

                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={isTabActive}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono transition-all whitespace-nowrap cursor-pointer ${
                      isTabActive
                        ? "bg-[#142032] text-sky-300 border border-[#213550] font-semibold"
                        : "text-slate-400 hover:text-slate-200 hover:bg-[#101928] border border-transparent"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5 text-sky-400" />
                    <span>{tab.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Tab content area */}
            <div className="p-4 sm:p-5">
              {(activeTab === "findings" || activeTab === "graph") && (
                <FindingsTable
                  entities={investigation.entities || []}
                  graph={graph}
                  onViewInMap={handleViewInMap}
                  onInspectNode={inspectNode}
                />
              )}

              {activeTab === "timeline" && (
                <DiscoveryTimeline
                  investigation={investigation}
                  isRunning={isRunning}
                  onInspectNode={inspectNode}
                  onViewInMap={handleViewInMap}
                />
              )}

              {activeTab === "analysis" && (
                <AnalysisNotebook investigation={investigation} onSaved={loadData} />
              )}

              {activeTab === "console" && (
                <LiveConsole
                  stream={stream}
                  isFinished={investigation.status === "completed" || investigation.status === "failed"}
                  onViewTrace={handleViewTrace}
                />
              )}
            </div>
          </div>
        </div>
      )}
        {(selectedWorkspaceNode || selectedWorkspaceEdge) && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-end bg-[#020712]/70 p-3 sm:p-4 backdrop-blur-sm animate-fade-in"
            role="dialog"
            aria-modal="true"
            aria-label="Inspector de entidad"
            onClick={(event) => {
              if (event.currentTarget === event.target) closeWorkspaceInspector();
            }}
          >
            <div className="h-full max-h-[calc(100vh-1.5rem)] w-full max-w-[420px] sm:max-h-[calc(100vh-2rem)]">
              <div className="h-full" onClick={(event) => event.stopPropagation()}>
                {selectedWorkspaceNode ? (
                  <EntityInspector
                    node={selectedWorkspaceNode}
                    nodes={workspaceNodes}
                    edges={workspaceEdges}
                    onClose={closeWorkspaceInspector}
                    onSelectNode={selectInspectorNode}
                    relationLabel={(edge) => getFriendlyRelationLabel(edge.relation_type, edge.label)}
                    containerMode="embedded"
                  />
                ) : selectedWorkspaceEdge ? (
                  <RelationshipInspector
                    edge={selectedWorkspaceEdge}
                    nodes={workspaceNodes}
                    onClose={closeWorkspaceInspector}
                    onSelectNode={selectInspectorNode}
                    relationLabel={(edge) => getFriendlyRelationLabel(edge.relation_type, edge.label)}
                    containerMode="embedded"
                  />
                ) : null}
              </div>
            </div>
          </div>
        )}
    </div>
  );
}
