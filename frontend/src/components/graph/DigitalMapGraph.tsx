"use client";

import { createElement, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  getViewportForBounds,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useStore,
  useStoreApi,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  User,
  ExternalLink,
  Filter,
  Link2,
  AlertTriangle,
  Network,
  Eye,
  EyeOff,
  Sparkles,
} from "lucide-react";
import { getGraphmlUrl, getInvestigationGraph } from "@/lib/api";
import { getEntityTypeMeta, getFindingIcon, buildEntityFilters } from "@/lib/entityTypes";
import { layoutDigitalMap, type LayoutCluster, type MapLayout } from "@/lib/graphLayout";
import type { GraphEdge, GraphNode, GraphNodeData, GraphResponse } from "@/lib/types";

// Tipos para React Flow
type DisplayNode = Node<Record<string, any>>;
type DisplayEdge = Edge<Record<string, any>>;

const RELATION_LABELS: Record<string, string> = {
  discovered_from: "Origen",
  shares_declared_email: "Mismo correo declarado",
  explicit_profile_link: "Enlace explícito de perfil",
  same_username: "Mismo nombre de usuario",
  similar_avatar: "Avatar coincidente",
};

function relationLabel(relationType: string): string {
  return (
    RELATION_LABELS[relationType] ??
    relationType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

// 1. Nodo Central: Identidad Objetivo (Estilo SpiderFoot + Nuestra Esencia)
function PersonRootNode({ data }: { data: any }) {
  const meta = (data.metadata_info || {}) as Record<string, any>;
  return (
    <div className="px-4 py-3.5 rounded-xl bg-[#131d2e] border-2 border-sky-400 shadow-2xl shadow-sky-950/80 min-w-[210px] text-center select-none transition-all hover:border-sky-300">
      <Handle type="source" position={Position.Top} id="top" className="!bg-sky-400 !w-2 !h-2" />
      <Handle type="source" position={Position.Right} id="right" className="!bg-sky-400 !w-2 !h-2" />
      <Handle type="source" position={Position.Bottom} id="bottom" className="!bg-sky-400 !w-2 !h-2" />
      <Handle type="source" position={Position.Left} id="left" className="!bg-sky-400 !w-2 !h-2" />

      <div className="w-11 h-11 rounded-full bg-sky-500/20 border border-sky-400/50 flex items-center justify-center mx-auto mb-2 text-sky-300 shadow-md shadow-sky-900/40">
        <User className="w-5 h-5" />
      </div>

      <div className="text-xs font-bold text-slate-100 font-mono tracking-tight truncate px-1">
        {String(data.label || "Identidad Objetivo")}
      </div>

      {meta.username && (
        <div className="text-[11px] text-sky-300/90 font-mono truncate mt-0.5">
          @{String(meta.username)}
        </div>
      )}

      {meta.university && (
        <div className="text-[10px] text-slate-300/80 font-mono truncate mt-0.5">
          {String(meta.university)}
        </div>
      )}

      <div className="inline-flex items-center gap-1 text-[9px] font-mono uppercase tracking-widest text-sky-400 mt-2 px-2 py-0.5 rounded-full bg-sky-950/60 border border-sky-500/30 font-semibold">
        <Sparkles className="w-2.5 h-2.5" />
        <span>Identidad Objetivo</span>
      </div>
    </div>
  );
}

// 2. Nodo de Entidad Satélite
function CustomEntityNode({ data, selected }: { data: any; selected?: boolean }) {
  const meta = getEntityTypeMeta(data.entity_type);
  const icon = getFindingIcon(data.platform, data.entity_type);
  const source = data.platform || meta.label || "Hallazgo";

  const nodeClass = selected
    ? "border-sky-400 ring-2 ring-sky-500/40 bg-[#172233] shadow-sky-950/70"
    : `${meta.node} hover:border-slate-400/50`;

  return (
    <div
      className={`px-3 py-2.5 rounded-lg border transition-all min-w-[190px] max-w-[220px] shadow-lg ${nodeClass} select-none`}
      title={meta.description}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !w-1.5 !h-1.5" />

      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 truncate">
          {createElement(icon, {
            className: `w-3.5 h-3.5 shrink-0 ${meta.accent}`,
            "aria-hidden": true,
          })}
          <span className="text-[10px] font-mono text-slate-300 uppercase tracking-wider truncate">
            {source}
          </span>
        </div>

        {data.isCorrelated && (
          <span
            title="Cuenta vinculada con otras del grupo"
            className="text-[9px] font-mono font-semibold px-1.5 py-0.2 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40"
          >
            Enlazada
          </span>
        )}
      </div>

      <div className="text-xs font-semibold text-slate-200 truncate" title={String(data.label || "")}>
        {String(data.label || "")}
      </div>

      {data.display_name && data.display_name !== data.label && (
        <div className="text-[10px] text-slate-400 truncate mt-0.5">
          {String(data.display_name)}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 mt-1.5 pt-1 border-t border-white/5">
        <span className={`text-[9px] font-mono uppercase tracking-wide ${meta.accent}`}>
          {meta.label}
        </span>
      </div>
    </div>
  );
}

// 3. Contenedor de Grupo / Cluster (Acelerado por hardware, sin lag)
function ClusterBackdropNode({ data }: { data: any }) {
  const isCorrelated = data.isCorrelated;
  const color = data.color || (isCorrelated ? "#a855f7" : "#64748b");

  return (
    <div
      className="rounded-2xl border transition-all pointer-events-none select-none"
      style={{
        width: data.width,
        height: data.height,
        borderColor: isCorrelated ? "rgba(168, 85, 247, 0.45)" : "rgba(100, 116, 139, 0.25)",
        backgroundColor: isCorrelated ? "rgba(168, 85, 247, 0.04)" : "rgba(30, 41, 59, 0.12)",
        borderStyle: isCorrelated ? "dashed" : "solid",
        borderWidth: 1.5,
      }}
    >
      <div className="px-3.5 py-2 flex items-center justify-between border-b border-white/5 bg-[#0b0f17]/60 rounded-t-2xl">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden="true"
          />
          <span
            className="text-[11px] font-mono font-bold tracking-wide uppercase"
            style={{ color: isCorrelated ? "#e9d5ff" : "#cbd5e1" }}
          >
            {data.label}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/10 text-slate-300 font-bold">
            {data.size}
          </span>
        </div>
        <span className="text-[10px] font-mono text-slate-400">
          {data.hint}
        </span>
      </div>
    </div>
  );
}

// Encuadre automático suave
function FitToLayout({ bounds }: { bounds: MapLayout["bounds"] }) {
  const store = useStoreApi();
  const { setViewport } = useReactFlow();
  const ready = useStore((state) => state.width > 0 && state.height > 0 && Boolean(state.panZoom));

  useEffect(() => {
    if (!ready) return;
    const { width, height, minZoom, maxZoom } = store.getState();
    setViewport(
      getViewportForBounds(bounds, width, height, minZoom, maxZoom, { x: "120px", y: "60px" }),
      { duration: 400 }
    );
  }, [bounds, ready, setViewport, store]);

  return null;
}

// Estilos de aristas
function edgeStyle(edge: GraphEdge) {
  if (edge.relation_type === "discovered_from") {
    return {
      stroke: "#38bdf8",
      strokeOpacity: 0.25,
      strokeWidth: 1,
      strokeDasharray: "4 6",
    };
  }
  if (edge.relation_type === "shares_declared_email") {
    return { stroke: "#10b981", strokeWidth: 2.5, strokeOpacity: 0.95 };
  }
  if (edge.relation_type === "explicit_profile_link") {
    return { stroke: "#a855f7", strokeWidth: 2.5, strokeOpacity: 0.95 };
  }
  if (edge.relation_type === "same_username") {
    return { stroke: "#f59e0b", strokeWidth: 2, strokeDasharray: "5 5", strokeOpacity: 0.9 };
  }
  if (edge.relation_type === "similar_avatar") {
    return { stroke: "#f97316", strokeWidth: 2, strokeDasharray: "3 3", strokeOpacity: 0.9 };
  }
  return {
    stroke: edge.supports_group ? "#a855f7" : "#38bdf8",
    strokeWidth: 2,
    strokeOpacity: 0.85,
  };
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
  const [nodes, setNodes, onNodesChange] = useNodesState<DisplayNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<DisplayEdge>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<DisplayNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [showDiscoveryLines, setShowDiscoveryLines] = useState(true);

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      const data: GraphResponse = await getInvestigationGraph(investigationId);
      setAllNodes(data.nodes || []);
      setAllEdges(data.edges || []);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el mapa digital");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph, refreshKey]);

  // Filtros de categorías
  const categories = useMemo(
    () =>
      buildEntityFilters(
        allNodes.filter((n) => n.type !== "personRoot").map((n) => n.data?.entity_type)
      ),
    [allNodes]
  );

  // Tipos de relación presentes
  const relationTypes = useMemo(
    () => [
      ...new Set(
        allEdges
          .filter((e) => e.relation_type !== "discovered_from")
          .map((e) => e.relation_type)
      ),
    ],
    [allEdges]
  );

  const view = useMemo(() => {
    const isRoot = (n: GraphNode) => n.type === "personRoot" || n.data?.is_root;
    const root = allNodes.find(isRoot);

    const visibleEntities = allNodes.filter(
      (n) => !isRoot(n) && (activeCategory === "all" || n.data?.entity_type === activeCategory)
    );

    const visibleIds = new Set(visibleEntities.map((n) => n.id));
    if (root) visibleIds.add(root.id);

    // Aristas visibles
    const visibleEdges = allEdges.filter((edge) => {
      if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return false;
      if (edge.relation_type === "discovered_from" && !showDiscoveryLines) return false;
      return true;
    });

    // Calcular layout SpiderFoot radial
    const layout = layoutDigitalMap(
      root?.id ?? "",
      visibleEntities.map((n) => ({
        id: n.id,
        label: n.data?.label,
        entityType: n.data?.entity_type,
        platform: n.data?.platform,
        groupId: n.data?.group_id,
        metadata: n.data?.metadata_info,
      })),
      allEdges.map((e) => ({
        source: e.source,
        target: e.target,
        relationType: e.relation_type,
        supportsGroup: e.supports_group,
      }))
    );

    // Nodos de React Flow
    const displayNodes: DisplayNode[] = [];

    // 1. Agregar cajas de fondo de clusters (renderizadas como nodos zIndex: -1 para aceleración GPU)
    layout.clusters.forEach((cluster) => {
      displayNodes.push({
        id: `cluster-bg-${cluster.id}`,
        type: "clusterBackdrop",
        position: { x: cluster.bounds.x, y: cluster.bounds.y },
        data: {
          width: cluster.bounds.width,
          height: cluster.bounds.height,
          label: cluster.label,
          hint: cluster.hint,
          size: cluster.size,
          isCorrelated: cluster.isCorrelated,
          color: cluster.color,
        },
        selectable: false,
        draggable: false,
        deletable: false,
        zIndex: -1,
      });
    });

    // 2. Nodo raíz Identidad Objetivo
    if (root) {
      displayNodes.push({
        ...root,
        type: "personRoot",
        position: layout.positions.get(root.id) ?? { x: 0, y: 0 },
        zIndex: 10,
      });
    }

    // 3. Nodos de entidades con posiciones calculadas
    const correlatedIdSet = new Set(
      allEdges
        .filter((e) => e.relation_type !== "discovered_from")
        .flatMap((e) => [e.source, e.target])
    );

    visibleEntities.forEach((entity) => {
      displayNodes.push({
        ...entity,
        type: "customEntity",
        position: layout.positions.get(entity.id) ?? { x: 0, y: 0 },
        data: {
          ...entity.data,
          isCorrelated: correlatedIdSet.has(entity.id) || Boolean(entity.data?.group_id),
        },
        zIndex: 5,
      });
    });

    // 4. Aristas con estilos específicos
    const displayEdges: DisplayEdge[] = visibleEdges.map((edge) => {
      const isDiscovery = edge.relation_type === "discovered_from";
      return {
        ...edge,
        data: edge,
        label: isDiscovery ? undefined : relationLabel(edge.relation_type),
        animated: edge.relation_type === "shares_declared_email" || edge.relation_type === "explicit_profile_link",
        style: edgeStyle(edge),
        labelStyle: { fill: "#e2e8f0", fontSize: 10, fontFamily: "ui-monospace, monospace", fontWeight: 600 },
        labelBgStyle: { fill: "#0f172a", fillOpacity: 0.95, stroke: "#334155", strokeWidth: 1 },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 4,
        zIndex: isDiscovery ? 1 : 2,
      };
    });

    return { nodes: displayNodes, edges: displayEdges, layout };
  }, [allNodes, allEdges, activeCategory, showDiscoveryLines]);

  useEffect(() => {
    setNodes(view.nodes);
    setEdges(view.edges);
  }, [setEdges, setNodes, view]);

  const nodeTypes = useMemo(
    () => ({
      personRoot: PersonRootNode,
      customEntity: CustomEntityNode,
      clusterBackdrop: ClusterBackdropNode,
    }),
    []
  );

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

  const entityCount = allNodes.filter((n) => n.type !== "personRoot" && !n.data?.is_root).length;
  const correlatedCount = view.layout.clusters.filter((c) => c.isCorrelated).length;

  return (
    <div className="h-[680px] w-full panel-card relative flex flex-col overflow-hidden border border-[#1e293b]">
      {/* Top Filter Bar */}
      <div className="px-4 py-3 bg-[#0d131f] border-b border-[#212f45] flex flex-wrap items-center justify-between gap-3 z-10">
        <div className="flex items-center gap-2 overflow-x-auto">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-sky-400 bg-sky-950/40 px-2.5 py-1 rounded border border-sky-500/30 shrink-0">
            <Filter className="w-3.5 h-3.5" aria-hidden="true" />
            <span>CAPAS:</span>
          </div>
          {categories.map((category) => {
            const meta = getEntityTypeMeta(category.id);
            const Icon = category.id === "all" ? null : meta.Icon;
            return (
              <button
                key={category.id}
                type="button"
                onClick={() => setActiveCategory(category.id)}
                title={category.description}
                aria-pressed={activeCategory === category.id}
                className={`flex items-center gap-1.5 text-xs font-mono px-3 py-1 rounded-md transition-all whitespace-nowrap cursor-pointer border ${
                  activeCategory === category.id
                    ? "bg-sky-500 text-white font-bold shadow-md shadow-sky-950 border-sky-400"
                    : "bg-[#151e2c] text-slate-300 hover:text-white hover:bg-[#1e2b3e] border-[#2b3a52]"
                }`}
              >
                {Icon && (
                  <Icon
                    className={`w-3.5 h-3.5 ${
                      activeCategory === category.id ? "text-white" : meta.accent
                    }`}
                    aria-hidden="true"
                  />
                )}
                <span>{category.label}</span>
                <span className="opacity-70">{category.count}</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-3">
          {/* Toggle para líneas de origen (discovered_from) */}
          <button
            type="button"
            onClick={() => setShowDiscoveryLines((prev) => !prev)}
            title={
              showDiscoveryLines
                ? "Ocultar líneas tenues desde el objetivo para ver solo correlaciones"
                : "Mostrar ramas desde el objetivo central"
            }
            className={`flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded-md border transition-colors cursor-pointer ${
              showDiscoveryLines
                ? "bg-sky-950/60 text-sky-300 border-sky-500/40"
                : "bg-[#151e2c] text-slate-400 border-[#2b3a52] hover:text-slate-200"
            }`}
          >
            {showDiscoveryLines ? (
              <Eye className="w-3.5 h-3.5 text-sky-400" />
            ) : (
              <EyeOff className="w-3.5 h-3.5 text-slate-400" />
            )}
            <span>Ramas objetivo</span>
          </button>

          {correlatedCount > 0 && (
            <span className="text-xs font-mono font-bold text-purple-300 bg-purple-950/50 px-2.5 py-1 rounded border border-purple-500/30">
              {correlatedCount} grupo(s) correlacionado(s)
            </span>
          )}

          <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-950/40 px-2.5 py-1 rounded border border-emerald-500/30">
            {entityCount} entidades
          </span>

          <button
            type="button"
            onClick={exportGraphJson}
            title="Exportar topología de grafo en JSON"
            className="text-xs font-mono px-3 py-1 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 border border-[#2b3a52] transition-colors cursor-pointer"
          >
            Grafo (JSON)
          </button>
          <button
            type="button"
            onClick={() => window.open(getGraphmlUrl(investigationId), "_blank")}
            title="Descargar archivo .graphml para Gephi / Cytoscape"
            className="text-xs font-mono px-3 py-1 rounded-md bg-purple-950/60 hover:bg-purple-900/70 text-purple-200 border border-purple-500/40 transition-colors cursor-pointer"
          >
            Gephi (.graphml)
          </button>
        </div>
      </div>

      {/* Canvas y Panel Lateral */}
      <div className="flex-1 flex min-h-0">
        <div className="flex-1 h-full relative min-w-0">
          {loading && (
            <div
              role="status"
              className="absolute inset-0 flex items-center justify-center bg-[#0b0f17]/80 z-20 text-xs font-mono text-slate-300"
            >
              <span
                className="w-4 h-4 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mr-2"
                aria-hidden="true"
              />
              Construyendo mapa radial SpiderFoot...
            </div>
          )}

          {!loading && error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0b0f17]/90 z-20 px-6 text-center">
              <AlertTriangle className="w-8 h-8 text-rose-400 mb-2" aria-hidden="true" />
              <p className="text-xs font-mono text-slate-200 font-semibold">
                No se pudo cargar el mapa digital
              </p>
              <p className="text-[11px] text-slate-400 mt-1 max-w-sm">{error}</p>
              <button
                type="button"
                onClick={loadGraph}
                className="mt-3 px-3 py-1.5 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors cursor-pointer"
              >
                Reintentar
              </button>
            </div>
          )}

          {!loading && !error && nodes.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0b0f17]/90 z-20 px-6 text-center">
              <p className="text-xs font-mono text-slate-300">
                No hay nodos para los filtros actuales.
              </p>
            </div>
          )}

          <ReactFlow<DisplayNode, DisplayEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => {
              if (node.type !== "clusterBackdrop") {
                setSelectedNode(node);
                setSelectedEdge(null);
              }
            }}
            onEdgeClick={(_, edge) => {
              setSelectedEdge(edge.data as GraphEdge ?? null);
              setSelectedNode(null);
            }}
            nodeOrigin={[0.5, 0.5]}
            minZoom={0.05}
            maxZoom={1.5}
            onlyRenderVisibleElements={true}
            elevateEdgesOnSelect={false}
          >
            <Background color="#1e293b" gap={20} size={1} />
            <FitToLayout bounds={view.layout.bounds} />
            <Controls className="!bg-[#121824] !border-[#212d40] !text-slate-200" />
            <MiniMap
              className="!bg-[#0d121c] !border-[#1e293b] rounded-md"
              nodeColor={(node) =>
                node.type === "personRoot"
                  ? "#38bdf8"
                  : node.data?.isCorrelated
                  ? "#a855f7"
                  : "#64748b"
              }
            />
          </ReactFlow>

          {/* Leyenda SpiderFoot en esquina inferior */}
          {!loading && !error && view.layout.clusters.length > 0 && (
            <div className="absolute bottom-3 left-14 z-10 max-w-[310px] px-3 py-2.5 rounded-lg bg-[#0d131f]/95 border border-[#212f45] text-[10px] leading-snug text-slate-400 pointer-events-none shadow-xl">
              <div className="flex items-center gap-1.5 font-bold text-slate-200 mb-1">
                <Network className="w-3 h-3 text-sky-400" />
                <span>Mapa de Correlación Radial</span>
              </div>
              <p>
                <strong className="text-purple-300">Constelaciones púrpuras:</strong> Cuentas
                que correlacionan entre sí por correo, alias o enlaces directos.
              </p>
              <p className="mt-1">
                <strong className="text-sky-300">Ramas desde objetivo:</strong> Desprenden del
                nodo central hacia los grupos de evidencias.
              </p>
            </div>
          )}
        </div>

        {/* Panel lateral: Detalle de entidad seleccionada */}
        {selectedNode && (
          <aside
            aria-label="Detalle de la entidad seleccionada"
            className="w-72 lg:w-80 border-l border-[#1e293b] bg-[#0e131d] p-4 overflow-y-auto shrink-0 shadow-2xl"
          >
            <div className="flex items-center justify-between pb-3 border-b border-[#1e293b] mb-4">
              <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
                {selectedNode.type === "personRoot" ? "Identidad Objetivo" : "Detalle de Entidad"}
              </h4>
              <button
                type="button"
                onClick={() => setSelectedNode(null)}
                className="text-xs font-mono text-slate-500 hover:text-slate-300"
              >
                Cerrar ✕
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Etiqueta</span>
                <span className="font-semibold text-slate-200 font-mono text-sm break-all">
                  {selectedNode.data?.label || selectedNode.data?.value}
                </span>
              </div>

              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Tipo</span>
                <span className="text-slate-300">
                  {selectedNode.type === "personRoot"
                    ? "Identidad Objetivo"
                    : getEntityTypeMeta(selectedNode.data?.entity_type).label}
                </span>
              </div>

              {selectedNode.data?.platform && (
                <div>
                  <span className="text-[10px] font-mono text-slate-500 uppercase block">Plataforma</span>
                  <span className="font-semibold text-sky-300">
                    {selectedNode.data.platform}
                  </span>
                </div>
              )}

              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Valor / Enlace</span>
                {selectedNode.data?.value?.startsWith("http") ? (
                  <a
                    href={selectedNode.data.value}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sky-400 hover:underline flex items-center gap-1 break-all mt-0.5"
                  >
                    <span className="truncate">{selectedNode.data.value}</span>
                    <ExternalLink className="w-3 h-3 shrink-0" aria-hidden="true" />
                  </a>
                ) : (
                  <span className="font-mono text-slate-300 break-all">
                    {selectedNode.data?.value}
                  </span>
                )}
              </div>

              {selectedNode.data?.isCorrelated && (
                <div className="p-2.5 rounded-md bg-purple-950/30 border border-purple-500/30 text-purple-200 text-[11px]">
                  <span className="font-bold flex items-center gap-1 mb-0.5">
                    <Link2 className="w-3.5 h-3.5 text-purple-400" />
                    Cuenta Correlacionada
                  </span>
                  Esta cuenta comparte evidencias (mismo correo, alias o enlace cruzado) con otras cuentas del grupo.
                </div>
              )}

              {typeof selectedNode.data?.metadata_info?.bio === "string" && (
                <div>
                  <span className="text-[10px] font-mono text-slate-500 uppercase block">
                    Biografía / Snippet
                  </span>
                  <p className="text-slate-300 text-[11px] mt-0.5 bg-[#141b28] p-2 rounded border border-[#1e293b]">
                    {selectedNode.data.metadata_info.bio}
                  </p>
                </div>
              )}

              {Array.isArray(selectedNode.data?.metadata_info?.extracted_emails) &&
                selectedNode.data.metadata_info.extracted_emails.length > 0 && (
                  <div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase block">
                      Correos Extraídos
                    </span>
                    <ul className="list-disc list-inside text-sky-400 text-[11px] mt-0.5 font-mono">
                      {selectedNode.data.metadata_info.extracted_emails.map((em: string) => (
                        <li key={em}>{em}</li>
                      ))}
                    </ul>
                  </div>
                )}
            </div>
          </aside>
        )}

        {/* Panel lateral: Detalle de arista seleccionada */}
        {selectedEdge && (
          <aside
            aria-label="Evidencia de la arista seleccionada"
            className="w-72 lg:w-80 border-l border-[#1e293b] bg-[#0e131d] p-4 overflow-y-auto shrink-0 shadow-2xl"
          >
            <div className="flex items-center justify-between pb-3 border-b border-[#1e293b] mb-4">
              <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
                Detalle de Relación
              </h4>
              <button
                type="button"
                onClick={() => setSelectedEdge(null)}
                className="text-xs font-mono text-slate-500 hover:text-slate-300"
              >
                Cerrar ✕
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">
                  Tipo de Relación
                </span>
                <span className="font-semibold text-slate-200 text-sm">
                  {relationLabel(selectedEdge.relation_type)}
                </span>
              </div>

              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">
                  Evidencia Vinculante
                </span>
                <div className="mt-1 bg-[#141b28] p-2.5 rounded border border-[#1e293b] text-slate-300 break-words font-mono text-[11px]">
                  {selectedEdge.evidence && typeof selectedEdge.evidence === "object" ? (
                    <pre className="whitespace-pre-wrap">
                      {JSON.stringify(selectedEdge.evidence, null, 2)}
                    </pre>
                  ) : (
                    <span>{String(selectedEdge.evidence || "Relación estructural")}</span>
                  )}
                </div>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
