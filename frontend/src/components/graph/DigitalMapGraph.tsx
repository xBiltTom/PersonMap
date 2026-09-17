"use client";

import { createElement, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  Braces,
  ExternalLink,
  Eye,
  EyeOff,
  FileDown,
  Filter,
  Network,
  User,
  X,
} from "lucide-react";
import { getGraphmlUrl, getInvestigationGraph } from "@/lib/api";
import { buildEntityFilters, getEntityTypeMeta, getFindingIcon } from "@/lib/entityTypes";
import { layoutDigitalMap } from "@/lib/graphLayout";
import type { GraphEdge, GraphNode, GraphNodeData, GraphResponse } from "@/lib/types";

type InteractionState = "idle" | "focused" | "dimmed";

interface DisplayNodeData extends GraphNodeData {
  interaction: InteractionState;
  isCorrelated: boolean;
  labelSide: "left" | "right";
}

type DisplayNode = Node<DisplayNodeData>;
type DisplayEdge = Edge<GraphEdge>;

const RELATION_LABELS: Record<string, string> = {
  discovered_from: "Procedencia",
  shares_declared_email: "Correo declarado compartido",
  explicit_profile_link: "Enlace explícito",
  same_username: "Alias coincidente",
  similar_avatar: "Avatar coincidente",
  same_platform: "Misma plataforma",
};

const RELATION_COLORS: Record<string, string> = {
  discovered_from: "#38bdf8",
  shares_declared_email: "#34d399",
  explicit_profile_link: "#a78bfa",
  same_username: "#22d3ee",
  similar_avatar: "#fb923c",
  same_platform: "#818cf8",
};

const HANDLE_POSITIONS = [Position.Top, Position.Right, Position.Bottom, Position.Left];

function relationLabel(relationType: string): string {
  return (
    RELATION_LABELS[relationType] ??
    relationType.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase())
  );
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function NodeHandles() {
  return (
    <>
      {HANDLE_POSITIONS.map((position) => (
        <Handle
          key={`source-${position}`}
          id={`source-${position}`}
          type="source"
          position={position}
          className="!h-1 !w-1 !border-0 !bg-transparent !opacity-0"
        />
      ))}
      {HANDLE_POSITIONS.map((position) => (
        <Handle
          key={`target-${position}`}
          id={`target-${position}`}
          type="target"
          position={position}
          className="!h-1 !w-1 !border-0 !bg-transparent !opacity-0"
        />
      ))}
    </>
  );
}

function PersonRootNode({ data, selected }: NodeProps<DisplayNode>) {
  const metadata = data.metadata_info ?? {};
  const username = textValue(metadata.username);

  return (
    <div className="relative flex h-[112px] w-[208px] select-none flex-col items-center justify-center">
      <NodeHandles />
      <div
        className={`absolute top-0 h-[72px] w-[72px] rounded-full border transition-all duration-200 ${
          selected
            ? "border-cyan-200/90 bg-cyan-400/20 shadow-[0_0_40px_rgba(34,211,238,0.35)]"
            : "border-cyan-300/65 bg-[#0b1c28] shadow-[0_0_28px_rgba(34,211,238,0.2)]"
        }`}
      >
        <span className="absolute inset-[-8px] rounded-full border border-cyan-400/15" />
        <span className="absolute inset-[-17px] rounded-full border border-dashed border-cyan-400/10" />
        <span className="absolute inset-0 flex items-center justify-center text-cyan-100">
          <User className="h-7 w-7" strokeWidth={1.45} aria-hidden="true" />
        </span>
      </div>
      <div className="absolute bottom-0 max-w-[208px] text-center">
        <p className="truncate font-mono text-[12px] font-semibold tracking-tight text-slate-50">
          {String(data.label || "Objetivo")}
        </p>
        <p className="mt-0.5 font-mono text-[8px] uppercase tracking-[0.22em] text-cyan-300/70">
          {username ? `@${username}` : "punto de partida"}
        </p>
      </div>
    </div>
  );
}

function EntityNode({ data, selected }: NodeProps<DisplayNode>) {
  const meta = getEntityTypeMeta(data.entity_type);
  const Icon = getFindingIcon(data.platform, data.entity_type);
  const source = data.platform || meta.label;
  const labelOnLeft = data.labelSide === "left";

  return (
    <div
      className={`relative flex h-[58px] w-[176px] select-none items-center gap-2.5 ${
        labelOnLeft ? "flex-row-reverse text-right" : "text-left"
      }`}
      title={meta.description}
    >
      <NodeHandles />
      <div
        className={`relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border bg-[#0c1420] transition-all duration-150 ${
          selected || data.interaction === "focused"
            ? "border-cyan-300/90 text-cyan-100 shadow-[0_0_22px_rgba(34,211,238,0.28)]"
            : "border-slate-500/45 text-slate-300 shadow-[0_0_14px_rgba(15,23,42,0.7)]"
        }`}
      >
        {createElement(Icon, { className: `h-4 w-4 ${meta.accent}`, "aria-hidden": true })}
        {data.isCorrelated && (
          <span
            className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#070b12] bg-violet-400"
            title="Tiene vínculos de evidencia con otros hallazgos"
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-[11px] font-medium leading-tight text-slate-200" title={data.label}>
          {data.label}
        </p>
        <p className={`mt-1 truncate font-mono text-[8px] uppercase tracking-[0.16em] ${meta.accent}`}>
          {source}
        </p>
      </div>
    </div>
  );
}

function FitToLayout({ layoutKey }: { layoutKey: string }) {
  const { fitView } = useReactFlow();

  useEffect(() => {
    const fitTimer = window.setTimeout(() => {
      void fitView({ padding: 0.14, duration: 450, maxZoom: 1.05 });
    }, 50);
    return () => window.clearTimeout(fitTimer);
  }, [fitView, layoutKey]);

  return null;
}

function edgeHandles(
  source: { x: number; y: number },
  target: { x: number; y: number }
): { sourceHandle: string; targetHandle: string } {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  if (Math.abs(dx) > Math.abs(dy)) {
    return dx >= 0
      ? { sourceHandle: `source-${Position.Right}`, targetHandle: `target-${Position.Left}` }
      : { sourceHandle: `source-${Position.Left}`, targetHandle: `target-${Position.Right}` };
  }
  return dy >= 0
    ? { sourceHandle: `source-${Position.Bottom}`, targetHandle: `target-${Position.Top}` }
    : { sourceHandle: `source-${Position.Top}`, targetHandle: `target-${Position.Bottom}` };
}

function edgeAppearance(
  edge: GraphEdge,
  evidenceEdgeCount: number,
  state: "idle" | "focused" | "dimmed"
) {
  const isDiscovery = edge.relation_type === "discovered_from";
  const color = RELATION_COLORS[edge.relation_type] ?? (edge.supports_group ? "#a78bfa" : "#64748b");
  const baseOpacity = isDiscovery
    ? 0.12
    : evidenceEdgeCount > 180
      ? 0.08
      : evidenceEdgeCount > 60
        ? 0.16
        : 0.48;

  return {
    stroke: color,
    strokeWidth: state === "focused" ? 1.9 : isDiscovery ? 0.7 : evidenceEdgeCount > 180 ? 0.65 : 1.05,
    strokeOpacity: state === "dimmed" ? 0.025 : state === "focused" ? 0.9 : baseOpacity,
    strokeDasharray: isDiscovery ? "3 8" : edge.relation_type === "similar_avatar" ? "3 5" : undefined,
    transition: "stroke-opacity 140ms ease, stroke-width 140ms ease",
  };
}

function DetailPanel({
  node,
  edge,
  onClose,
}: {
  node: GraphNode | null;
  edge: GraphEdge | null;
  onClose: () => void;
}) {
  if (!node && !edge) return null;

  if (edge) {
    return (
      <aside className="absolute bottom-4 right-4 top-20 z-30 w-[min(320px,calc(100%-2rem))] overflow-y-auto rounded-xl border border-slate-700/70 bg-[#0a101a]/95 p-4 shadow-2xl backdrop-blur-md">
        <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-violet-300">Relación observada</p>
            <h4 className="mt-1 text-sm font-semibold text-slate-100">{relationLabel(edge.relation_type)}</h4>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white" aria-label="Cerrar detalle">
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mb-1 font-mono text-[9px] uppercase tracking-wider text-slate-500">Evidencia registrada</p>
        <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-[#070b12] p-3 font-mono text-[10px] leading-relaxed text-slate-300">
          {edge.evidence && typeof edge.evidence === "object"
            ? JSON.stringify(edge.evidence, null, 2)
            : String(edge.evidence || "Sin detalle adicional")}
        </pre>
      </aside>
    );
  }

  if (!node) return null;
  const metadata = node.data.metadata_info ?? {};
  const bio = textValue(metadata.bio);
  const isRoot = node.type === "personRoot" || node.data.is_root;
  const meta = getEntityTypeMeta(node.data.entity_type);

  return (
    <aside className="absolute bottom-4 right-4 top-20 z-30 w-[min(320px,calc(100%-2rem))] overflow-y-auto rounded-xl border border-slate-700/70 bg-[#0a101a]/95 p-4 shadow-2xl backdrop-blur-md">
      <div className="mb-4 flex items-start justify-between border-b border-slate-800 pb-3">
        <div className="min-w-0">
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-cyan-300">
            {isRoot ? "Punto de partida" : meta.label}
          </p>
          <h4 className="mt-1 break-words font-mono text-sm font-semibold text-slate-100">{node.data.label}</h4>
        </div>
        <button type="button" onClick={onClose} className="ml-2 rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white" aria-label="Cerrar detalle">
          <X className="h-4 w-4" />
        </button>
      </div>
      <dl className="space-y-3 text-xs">
        {node.data.platform && (
          <div>
            <dt className="font-mono text-[9px] uppercase tracking-wider text-slate-500">Fuente</dt>
            <dd className="mt-0.5 text-slate-200">{node.data.platform}</dd>
          </div>
        )}
        <div>
          <dt className="font-mono text-[9px] uppercase tracking-wider text-slate-500">Valor observado</dt>
          <dd className="mt-0.5 break-all font-mono text-[11px] text-slate-300">
            {node.data.value.startsWith("http") ? (
              <a href={node.data.value} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-cyan-300 hover:underline">
                {node.data.value}
                <ExternalLink className="h-3 w-3 shrink-0" />
              </a>
            ) : (
              node.data.value
            )}
          </dd>
        </div>
        {bio && (
          <div>
            <dt className="font-mono text-[9px] uppercase tracking-wider text-slate-500">Contexto público</dt>
            <dd className="mt-1 rounded-lg border border-slate-800 bg-[#070b12] p-2.5 text-[11px] leading-relaxed text-slate-300">{bio}</dd>
          </div>
        )}
      </dl>
    </aside>
  );
}

export function DigitalMapGraph({
  investigationId,
  refreshKey,
}: {
  investigationId: string;
  refreshKey?: string;
}) {
  const [allNodes, setAllNodes] = useState<GraphNode[]>([]);
  const [allEdges, setAllEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [showDiscoveryLines, setShowDiscoveryLines] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      const data: GraphResponse = await getInvestigationGraph(investigationId);
      setAllNodes(data.nodes || []);
      setAllEdges(data.edges || []);
      setError(null);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : "No se pudo cargar el mapa digital");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadGraph, refreshKey]);

  const categories = useMemo(
    () =>
      buildEntityFilters(
        allNodes.filter((node) => node.type !== "personRoot").map((node) => node.data.entity_type)
      ),
    [allNodes]
  );

  const baseView = useMemo(() => {
    const isRoot = (node: GraphNode) => node.type === "personRoot" || node.data.is_root;
    const root = allNodes.find(isRoot);
    const entities = allNodes.filter(
      (node) => !isRoot(node) && (activeCategory === "all" || node.data.entity_type === activeCategory)
    );
    const visibleIds = new Set(entities.map((node) => node.id));
    if (root) visibleIds.add(root.id);

    const candidateEdges = allEdges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)
    );
    const visibleEdges = candidateEdges.filter(
      (edge) => showDiscoveryLines || edge.relation_type !== "discovered_from"
    );
    const evidenceEdges = candidateEdges.filter(
      (edge) => edge.relation_type !== "discovered_from"
    );
    const degree = new Map<string, number>();
    for (const edge of evidenceEdges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }

    const layout = layoutDigitalMap(
      root?.id ?? "",
      entities.map((node) => ({ id: node.id, groupId: node.data.group_id })),
      candidateEdges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        relationType: edge.relation_type,
      }))
    );

    const nodes: DisplayNode[] = [];
    if (root) {
      nodes.push({
        ...root,
        type: "personRoot",
        position: layout.positions.get(root.id) ?? { x: 0, y: 0 },
        width: 208,
        height: 112,
        draggable: false,
        zIndex: 10,
        data: {
          ...root.data,
          interaction: "idle",
          isCorrelated: false,
          labelSide: "right",
        },
      });
    }

    for (const entity of entities) {
      const position = layout.positions.get(entity.id) ?? { x: 0, y: 0 };
      nodes.push({
        ...entity,
        type: "customEntity",
        position,
        width: 176,
        height: 58,
        draggable: false,
        zIndex: 5,
        data: {
          ...entity.data,
          interaction: "idle",
          isCorrelated: (degree.get(entity.id) ?? 0) > 0 || Boolean(entity.data.group_id),
          labelSide: position.x < -80 ? "left" : "right",
        },
      });
    }

    const persistentLabels = evidenceEdges.length <= 12;
    const edges: DisplayEdge[] = visibleEdges.map((edge) => {
      const source = layout.positions.get(edge.source) ?? { x: 0, y: 0 };
      const target = layout.positions.get(edge.target) ?? { x: 0, y: 0 };
      const isDiscovery = edge.relation_type === "discovered_from";
      return {
        ...edge,
        ...edgeHandles(source, target),
        type: "default",
        data: edge,
        label: !isDiscovery && persistentLabels ? relationLabel(edge.relation_type) : undefined,
        animated: false,
        interactionWidth: 18,
        style: edgeAppearance(edge, evidenceEdges.length, "idle"),
        labelStyle: {
          fill: "#cbd5e1",
          fontSize: 9,
          fontFamily: "ui-monospace, monospace",
          fontWeight: 500,
        },
        labelBgStyle: { fill: "#080d15", fillOpacity: 0.94, stroke: "#263449", strokeWidth: 0.5 },
        labelBgPadding: [5, 2],
        labelBgBorderRadius: 8,
        zIndex: isDiscovery ? 0 : 1,
      };
    });

    const layoutKey = `${activeCategory}:${entities.map((node) => node.id).join(",")}:${evidenceEdges
      .map((edge) => edge.id)
      .join(",")}`;

    return {
      nodes,
      edges,
      visibleEdges,
      evidenceEdgeCount: evidenceEdges.length,
      persistentLabels,
      layoutKey,
    };
  }, [activeCategory, allEdges, allNodes, showDiscoveryLines]);

  const view = useMemo(() => {
    const activeNodeId = hoveredNodeId ?? selectedNodeId;
    const focusedNodeIds = new Set<string>();
    if (activeNodeId) {
      focusedNodeIds.add(activeNodeId);
      for (const edge of baseView.visibleEdges) {
        if (edge.source === activeNodeId) focusedNodeIds.add(edge.target);
        if (edge.target === activeNodeId) focusedNodeIds.add(edge.source);
      }
    } else if (selectedEdgeId) {
      const selectedEdge = baseView.visibleEdges.find((edge) => edge.id === selectedEdgeId);
      if (selectedEdge) {
        focusedNodeIds.add(selectedEdge.source);
        focusedNodeIds.add(selectedEdge.target);
      }
    }
    const hasFocus = focusedNodeIds.size > 0;

    const nodes = baseView.nodes.map((node) => {
      const interaction: InteractionState = !hasFocus
        ? "idle"
        : focusedNodeIds.has(node.id)
          ? "focused"
          : "dimmed";
      return {
        ...node,
        selected: node.id === selectedNodeId,
        style: {
          opacity: interaction === "dimmed" ? 0.16 : 1,
          transition: "opacity 140ms ease",
        },
        data: { ...node.data, interaction },
      };
    });

    const edges = baseView.edges.map((edge) => {
      const rawEdge = edge.data as GraphEdge;
      const isFocused =
        edge.id === selectedEdgeId ||
        Boolean(activeNodeId && (edge.source === activeNodeId || edge.target === activeNodeId));
      const state = hasFocus ? (isFocused ? "focused" : "dimmed") : "idle";
      return {
        ...edge,
        selected: edge.id === selectedEdgeId,
        label:
          rawEdge.relation_type !== "discovered_from" &&
          (baseView.persistentLabels || edge.id === selectedEdgeId)
            ? relationLabel(rawEdge.relation_type)
            : undefined,
        style: edgeAppearance(rawEdge, baseView.evidenceEdgeCount, state),
        zIndex: isFocused ? 4 : edge.zIndex,
      };
    });

    return { nodes, edges };
  }, [baseView, hoveredNodeId, selectedEdgeId, selectedNodeId]);

  const nodeTypes = useMemo(
    () => ({ personRoot: PersonRootNode, customEntity: EntityNode }),
    []
  );

  const selectedNode = allNodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = allEdges.find((edge) => edge.id === selectedEdgeId) ?? null;
  const entityCount = allNodes.filter(
    (node) => node.type !== "personRoot" && !node.data.is_root
  ).length;
  const evidenceCount = allEdges.filter((edge) => edge.relation_type !== "discovered_from").length;
  const relationTypes = [
    ...new Set(
      allEdges
        .filter((edge) => edge.relation_type !== "discovered_from")
        .map((edge) => edge.relation_type)
    ),
  ];

  const exportGraphJson = () => {
    const blob = new Blob([JSON.stringify({ nodes: allNodes, edges: allEdges }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `graph-${investigationId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="digital-map-canvas relative h-[680px] w-full overflow-hidden rounded-xl border border-[#1a2636] bg-[#070b12] shadow-[inset_0_1px_0_rgba(255,255,255,0.025)] sm:h-[720px]">
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 bg-gradient-to-b from-[#070b12] via-[#070b12]/95 to-transparent px-3 pb-8 pt-3 sm:px-4">
        <div className="pointer-events-auto flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <span className="mr-1 flex shrink-0 items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500">
              <Filter className="h-3 w-3" /> Capas
            </span>
            {categories.map((category) => {
              const meta = getEntityTypeMeta(category.id);
              const Icon = category.id === "all" ? Network : meta.Icon;
              const active = activeCategory === category.id;
              return (
                <button
                  key={category.id}
                  type="button"
                  onClick={() => setActiveCategory(category.id)}
                  title={category.description}
                  aria-pressed={active}
                  className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9px] transition-colors ${
                    active
                      ? "border-cyan-400/55 bg-cyan-400/12 text-cyan-100"
                      : "border-slate-700/70 bg-[#0d1420]/85 text-slate-400 hover:border-slate-500 hover:text-slate-200"
                  }`}
                >
                  <Icon className={`h-3 w-3 ${active ? "text-cyan-300" : meta.accent}`} />
                  {category.label}
                  <span className="text-slate-500">{category.count}</span>
                </button>
              );
            })}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <span className="hidden font-mono text-[9px] text-slate-500 lg:inline">
              {entityCount} nodos · {evidenceCount} vínculos
            </span>
            <button
              type="button"
              onClick={() => setShowDiscoveryLines((visible) => !visible)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9px] transition-colors ${
                showDiscoveryLines
                  ? "border-cyan-400/45 bg-cyan-400/10 text-cyan-200"
                  : "border-slate-700/70 bg-[#0d1420]/85 text-slate-400 hover:text-slate-200"
              }`}
              title="Mostrar u ocultar la procedencia técnica de cada hallazgo"
              aria-pressed={showDiscoveryLines}
            >
              {showDiscoveryLines ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
              Procedencia
            </button>
            <button type="button" onClick={exportGraphJson} className="rounded-full border border-slate-700/70 bg-[#0d1420]/85 p-1.5 text-slate-400 hover:border-slate-500 hover:text-cyan-200" title="Exportar grafo JSON" aria-label="Exportar grafo JSON">
              <Braces className="h-3.5 w-3.5" />
            </button>
            <button type="button" onClick={() => window.open(getGraphmlUrl(investigationId), "_blank")} className="rounded-full border border-slate-700/70 bg-[#0d1420]/85 p-1.5 text-slate-400 hover:border-slate-500 hover:text-violet-200" title="Descargar GraphML" aria-label="Descargar GraphML">
              <FileDown className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {loading && (
        <div role="status" className="absolute inset-0 z-40 flex items-center justify-center bg-[#070b12]/90 font-mono text-xs text-slate-400">
          <span className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-cyan-400/20 border-t-cyan-300" />
          Trazando evidencia...
        </div>
      )}

      {!loading && error && (
        <div className="absolute inset-0 z-40 flex flex-col items-center justify-center bg-[#070b12]/95 px-6 text-center">
          <AlertTriangle className="mb-2 h-7 w-7 text-rose-400" />
          <p className="font-mono text-xs font-semibold text-slate-200">No se pudo cargar el mapa</p>
          <p className="mt-1 max-w-sm text-[11px] text-slate-500">{error}</p>
          <button type="button" onClick={() => void loadGraph()} className="mt-3 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono text-[10px] text-slate-200 hover:border-cyan-500/50">
            Reintentar
          </button>
        </div>
      )}

      {!loading && !error && view.nodes.length === 0 && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#070b12]/90 font-mono text-xs text-slate-400">
          No hay nodos para esta capa.
        </div>
      )}

      <ReactFlow<DisplayNode, DisplayEdge>
        nodes={view.nodes}
        edges={view.edges}
        nodeTypes={nodeTypes}
        nodeOrigin={[0.5, 0.5]}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.08}
        maxZoom={2.2}
        elevateEdgesOnSelect={false}
        onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
        onNodeMouseLeave={() => setHoveredNodeId(null)}
        onNodeClick={(_, node) => {
          setSelectedNodeId(node.id);
          setSelectedEdgeId(null);
        }}
        onEdgeClick={(_, edge) => {
          setSelectedEdgeId(edge.id);
          setSelectedNodeId(null);
        }}
        onPaneClick={() => {
          setSelectedNodeId(null);
          setSelectedEdgeId(null);
        }}
      >
        <Background variant={BackgroundVariant.Lines} color="#101a29" gap={36} size={0.45} />
        <FitToLayout layoutKey={baseView.layoutKey} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          position="bottom-right"
          pannable
          zoomable
          maskColor="rgba(3, 7, 13, 0.76)"
          nodeStrokeWidth={2}
          nodeColor={(node) =>
            node.type === "personRoot"
              ? "#22d3ee"
              : node.data?.isCorrelated
                ? "#8b5cf6"
                : "#475569"
          }
        />
      </ReactFlow>

      {!loading && !error && relationTypes.length > 0 && (
        <div className="pointer-events-none absolute bottom-3 left-14 z-10 hidden max-w-[55%] flex-wrap items-center gap-x-3 gap-y-1 rounded-full border border-slate-800/80 bg-[#080d15]/85 px-3 py-1.5 backdrop-blur sm:flex">
          {relationTypes.slice(0, 4).map((relationType) => (
            <span key={relationType} className="flex items-center gap-1.5 font-mono text-[8px] text-slate-500">
              <span className="h-px w-4" style={{ backgroundColor: RELATION_COLORS[relationType] ?? "#64748b" }} />
              {relationLabel(relationType)}
            </span>
          ))}
        </div>
      )}

      <DetailPanel
        node={selectedNode}
        edge={selectedEdge}
        onClose={() => {
          setSelectedNodeId(null);
          setSelectedEdgeId(null);
        }}
      />
    </div>
  );
}
