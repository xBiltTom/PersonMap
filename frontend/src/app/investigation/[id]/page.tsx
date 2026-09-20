"use client";

import { use, useEffect, useState, useCallback, useMemo, useRef } from "react";
import Link from "next/link";
import { GraphEdge, GraphNode, GraphResponse, InvestigationData } from "@/lib/types";
import { getInvestigation, getInvestigationGraph, getGraphmlUrl } from "@/lib/api";
import { ENGINE_META, resolveEngine } from "@/lib/engines";
import { DigitalMapGraph } from "@/components/graph/DigitalMapGraph";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { DiscoveryTimeline } from "@/components/timeline/DiscoveryTimeline";
import { LiveConsole } from "@/components/console/LiveConsole";
import { InvestigationProgress } from "@/components/console/InvestigationProgress";
import { useInvestigationStream } from "@/lib/useInvestigationStream";
import { ReportView } from "@/components/report/ReportView";
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
  FileText,
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
} from "lucide-react";

type WorkspaceSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string };

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
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const [copiedId, setCopiedId] = useState(false);
  const [isMapCollapsed, setIsMapCollapsed] = useState(false);
  const [workspaceSelection, setWorkspaceSelection] = useState<WorkspaceSelection | null>(null);

  const exportMenuRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);

  const loadData = useCallback(async () => {
    try {
      const data = await getInvestigation(id);
      setInvestigation(data);
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
      const targetName =
        investigation.target?.full_name ||
        investigation.target?.username ||
        investigation.target?.email ||
        "Objetivo Anónimo";

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
  }, [id, investigation?.completed_at, investigation?.entities?.length, investigation?.id, investigation?.status]);

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
    setWorkspaceSelection({ kind: "node", id: nodeId });
    setActiveTab("graph");
    // If map was collapsed, expand it
    setIsMapCollapsed(false);
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
  const stream = useInvestigationStream(id, handleStreamFinished);

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

  const handleCopyId = () => {
    if (!investigation) return;
    navigator.clipboard.writeText(investigation.id).then(() => {
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
      setIsMoreMenuOpen(false);
    });
  };

  // Metric computations (User Rule #3: Semantically distinct & completely factual)
  const findingsCount = investigation?.entities?.length ?? 0;
  // Unique resolved nodes (distinct from raw findings!)
  const uniqueNodesCount = useMemo(() => {
    if (graph?.nodes?.length) {
      return graph.nodes.filter((n) => !n.data?.is_root && n.type !== "personRoot").length;
    }
    return new Set((investigation?.entities || []).map((e) => e.value)).size;
  }, [graph, investigation?.entities]);

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

  const targetName =
    investigation.target?.full_name ||
    investigation.target?.username ||
    investigation.target?.email ||
    "Objetivo Anónimo";

  const code = `PM-${investigation.id.slice(0, 4).toUpperCase()}`;
  const isRunning = investigation.status === "running" || investigation.status === "pending";
  const isCompleted = investigation.status === "completed";
  const isFailed = investigation.status === "failed";
  const engineMeta = ENGINE_META[resolveEngine(investigation.strategy, investigation.metrics)];

  const lowerTabs = [
    { id: "findings", label: `Hallazgos (${findingsCount})`, icon: Table },
    { id: "timeline", label: "Línea de tiempo", icon: Clock },
    { id: "console", label: "Consola", icon: Terminal },
    { id: "report", label: "Informe", icon: FileText },
  ];

  return (
    <div className="space-y-4 max-w-7xl mx-auto">
      {/* 1. Dossier Header Bar (Exact match to referencia-frontend-refactor.png) */}
      <div className="panel-card p-4 sm:p-5 border border-[#162234] bg-[#0d1420]">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
          {/* Target Identity & Metadata */}
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-100 font-sans truncate">
                {targetName}
              </h1>
              {investigation.target?.university && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#131e2e] text-sky-300 border border-[#20324c]">
                  {investigation.target.university}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2.5 mt-1.5 text-xs font-mono text-slate-400">
              <span className="text-slate-300 font-medium">{code}</span>
              <span className="text-slate-600">|</span>
              <span>{formatDate(investigation.created_at)}</span>
              <span className="text-slate-600">|</span>
              <span className={`text-[10px] px-2 py-0.2 rounded border ${engineMeta.badge}`}>
                {engineMeta.label}
              </span>
            </div>

            {/* Quick target identifiers */}
            <div className="flex flex-wrap items-center gap-3 mt-2 text-[11px] font-mono text-slate-500">
              {investigation.target?.email && <span>📧 {investigation.target.email}</span>}
              {investigation.target?.username && <span>👤 @{investigation.target.username}</span>}
              {investigation.target?.dni && <span>🪪 DNI: {investigation.target.dni}</span>}
            </div>
          </div>

          {/* Metrics Strip + Status + Actions */}
          <div className="flex flex-wrap items-center gap-4 sm:gap-6 shrink-0 pt-2 xl:pt-0 border-t xl:border-t-0 border-[#162234]">
            {/* 4 Factual Metrics (Rule #3) */}
            <div className="grid grid-cols-4 gap-3 sm:gap-5 text-center">
              <div>
                <div className="font-mono text-base sm:text-lg font-bold text-slate-100">
                  {findingsCount}
                </div>
                <div className="text-[10px] font-mono text-slate-400">
                  Hallazgos
                </div>
              </div>

              <div>
                <div className="font-mono text-base sm:text-lg font-bold text-sky-400">
                  {uniqueNodesCount}
                </div>
                <div className="text-[10px] font-mono text-slate-400">
                  Entidades
                </div>
              </div>

              <div>
                <div className="font-mono text-base sm:text-lg font-bold text-slate-100">
                  {relationsCount}
                </div>
                <div className="text-[10px] font-mono text-slate-400">
                  Relaciones
                </div>
              </div>

              <div>
                <div className="font-mono text-base sm:text-lg font-bold text-slate-100">
                  {sourcesCount}
                </div>
                <div className="text-[10px] font-mono text-slate-400">
                  Fuentes
                </div>
              </div>
            </div>

            <div className="h-8 w-px bg-[#162234] hidden sm:block" />

            {/* Status Indicator */}
            <div className="flex items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border ${
                  isCompleted
                    ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                    : isRunning
                    ? "bg-sky-500/15 text-sky-300 border-sky-500/30 animate-pulse"
                    : isFailed
                    ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
                    : "bg-amber-500/15 text-amber-300 border-amber-500/30"
                }`}
              >
                {isCompleted ? (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                ) : isRunning ? (
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <XCircle className="w-3.5 h-3.5" />
                )}
                <span>
                  {isCompleted
                    ? "Completado"
                    : isRunning
                    ? "En análisis"
                    : isFailed
                    ? "Fallido"
                    : investigation.status}
                </span>
              </span>

              {/* Export dropdown */}
              <div className="relative" ref={exportMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsExportOpen((prev) => !prev)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#142032] hover:bg-[#1c2e47] border border-[#213550] text-xs font-mono text-slate-200 transition-colors cursor-pointer"
                >
                  <Download className="w-3.5 h-3.5 text-sky-400" />
                  <span>Exportar informe</span>
                  <ChevronDown className="w-3 h-3 text-slate-400" />
                </button>

                {isExportOpen && (
                  <div className="absolute right-0 top-10 w-52 rounded-xl border border-[#22344d] bg-[#0c131f] p-1.5 shadow-2xl z-50 animate-fade-in font-mono text-xs">
                    <button
                      type="button"
                      onClick={handleExportJson}
                      className="flex w-full items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-[#162234] text-left transition-colors"
                    >
                      <Download className="w-3.5 h-3.5 text-sky-400" />
                      <span>Descargar JSON</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        window.print();
                        setIsExportOpen(false);
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-[#162234] text-left transition-colors"
                    >
                      <Printer className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Imprimir / PDF forense</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        window.open(getGraphmlUrl(investigation.id), "_blank");
                        setIsExportOpen(false);
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-[#162234] text-left transition-colors"
                    >
                      <FileDown className="w-3.5 h-3.5 text-purple-400" />
                      <span>Descargar GraphML</span>
                    </button>
                  </div>
                )}
              </div>

              {/* More options menu */}
              <div className="relative" ref={moreMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsMoreMenuOpen((prev) => !prev)}
                  className="p-2 rounded-lg bg-[#0e1624] hover:bg-[#162438] border border-[#1b2a3e] text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
                  title="Más opciones"
                >
                  ···
                </button>

                {isMoreMenuOpen && (
                  <div className="absolute right-0 top-10 w-48 rounded-xl border border-[#22344d] bg-[#0c131f] p-1.5 shadow-2xl z-50 animate-fade-in font-mono text-xs">
                    <button
                      type="button"
                      onClick={handleCopyId}
                      className="flex w-full items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-[#162234] text-left transition-colors"
                    >
                      {copiedId ? (
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-slate-400" />
                      )}
                      <span>{copiedId ? "ID copiado" : "Copiar ID"}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        loadData();
                        setIsMoreMenuOpen(false);
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-[#162234] text-left transition-colors"
                    >
                      <RefreshCw className="w-3.5 h-3.5 text-sky-400" />
                      <span>Recargar datos</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Real-time progress tracker when investigation is active */}
      {isRunning && (
        <InvestigationProgress
          stream={stream}
          startedAt={investigation.created_at}
          onOpenConsole={() => setActiveTab("console")}
        />
      )}

      {/* 2. Workspace. El inspector se consulta sobre el expediente sin reducir sus vistas. */}
      <div className="space-y-4">
        {/* Upper Card: Mapa Digital (Adaptive height + collapsible for 1366x768) */}
        <div className="panel-card overflow-hidden border border-[#162234] bg-[#0d1420] shadow-xl">
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

        {/* Lower Card: Workspace Multivista (Tabs + Findings/Timeline/Console/Report) */}
        <div className="panel-card overflow-hidden border border-[#162234] bg-[#0d1420] shadow-xl">
        {/* Workspace Subtabs */}
        <div
          role="tablist"
          aria-label="Vistas del expediente"
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
            <DiscoveryTimeline entities={investigation.entities || []} />
          )}

          {activeTab === "console" && (
            <LiveConsole
              stream={stream}
              isFinished={investigation.status === "completed" || investigation.status === "failed"}
            />
          )}

          {activeTab === "report" && (
            <ReportView investigation={investigation} />
          )}
        </div>
      </div>
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
    </div>
  );
}
