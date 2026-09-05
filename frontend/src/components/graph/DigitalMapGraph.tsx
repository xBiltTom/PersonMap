"use client";

import { createElement, useEffect, useState, useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GraphResponse } from "@/lib/types";
import { getGraphmlUrl, getInvestigationGraph } from "@/lib/api";
import {
  buildEntityFilters,
  getEntityTypeMeta,
  getFindingIcon,
} from "@/lib/entityTypes";
import { IdentityEvidence } from "@/components/identity/IdentityEvidence";
import { User, ExternalLink, AlertTriangle, Filter } from "lucide-react";

/**
 * Icono de un nodo. Delega en `lib/entityTypes`, que es la fuente única
 * compartida con la tabla de hallazgos: así un `entity_type` nuevo se
 * representa igual en ambas vistas sin tocar este fichero.
 */

// 1. Root Person Node Component
function PersonRootNode({ data }: { data: any }) {
  const meta = (data.metadata_info || {}) as Record<string, any>;
  return (
    <div className="px-4 py-3 rounded-lg bg-[#152033] border-2 border-sky-400 shadow-xl shadow-sky-950/50 min-w-[200px] text-center">
      <Handle type="source" position={Position.Bottom} className="!bg-sky-400 !w-2 !h-2" />
      <Handle type="target" position={Position.Top} className="!bg-sky-400 !w-2 !h-2" />
      
      <div className="w-10 h-10 rounded-full bg-sky-500/20 border border-sky-400/40 flex items-center justify-center mx-auto mb-2 text-sky-300">
        <User className="w-5 h-5" />
      </div>
      <div className="text-xs font-bold text-slate-100 font-mono tracking-tight truncate">
        {String(data.label || "")}
      </div>
      {meta.university && (
        <div className="text-[10px] text-sky-300/80 font-mono truncate mt-0.5">
          {String(meta.university)}
        </div>
      )}
      <div className="text-[9px] font-mono uppercase tracking-widest text-sky-400 mt-1 font-semibold">
        Identidad Objetivo
      </div>
    </div>
  );
}

// 2. Satellite Entity Node Component
/**
 * Los tres niveles de ATRIBUCIÓN, con los mismos umbrales que usa el resolutor
 * para formar los clusters. Que coincidan importa: si el grafo pintara un nodo
 * como seguro y la pestaña de identidad lo pusiera entre los descartados, el
 * expediente se contradiría a sí mismo.
 */
const CERTAINTY_TIERS = {
  attributed: {
    id: "attributed",
    label: "Atribuido",
    min: 0.7,
    badge: "bg-emerald-500/20 text-emerald-300",
    ring: "ring-1 ring-emerald-500/50",
    help: "El modelo atribuye este hallazgo a la persona investigada.",
  },
  probable: {
    id: "probable",
    label: "Probable",
    min: 0.4,
    badge: "bg-amber-500/15 text-amber-300",
    ring: "ring-1 ring-amber-500/30",
    help: "Evidencia parcial. Conviene confirmarlo o descartarlo a mano.",
  },
  discarded: {
    id: "discarded",
    label: "Descartado",
    min: 0,
    badge: "bg-slate-700/60 text-slate-400",
    ring: "",
    help:
      "Sin evidencia suficiente de pertenecer al objetivo. Coincidir en un alias " +
      "no basta: puede ser otra persona con el mismo nombre de usuario.",
  },
} as const;

type TierId = keyof typeof CERTAINTY_TIERS;

/**
 * Probabilidad de que el hallazgo sea del objetivo.
 *
 * Se lee `identity_score` y NO `confidence`. Son cosas distintas y el grafo
 * mostraba la equivocada: `confidence` es el máximo entre la certeza de
 * DETECCIÓN que reporta la herramienta ("esta cuenta existe") y la de
 * atribución. Medido sobre una investigación real de 312 nodos, el grafo pintaba
 * 184 como alta confianza mientras el modelo solo atribuía 32 — `TikTok:
 * @torvalds` salía al 90 % cuando su atribución era del 1 %.
 */
/** Lo mínimo que hace falta leer de un nodo para decidir su certeza. */
interface NodeCertainty {
  identity_score?: number | null;
  confidence?: number | null;
  existence_confidence?: number | null;
  verified?: boolean;
  metadata_info?: { identity_score?: number };
}

function attributionOf(data: NodeCertainty | undefined): number {
  const score = data?.identity_score ?? data?.metadata_info?.identity_score;
  if (typeof score === "number") return score;
  // Entidades anteriores a la separación de métricas.
  return Number(data?.confidence || 0);
}

function tierOf(data: NodeCertainty | undefined): TierId {
  if (Boolean(data?.verified)) return "attributed";
  const score = attributionOf(data);
  if (score >= CERTAINTY_TIERS.attributed.min) return "attributed";
  if (score >= CERTAINTY_TIERS.probable.min) return "probable";
  return "discarded";
}

function CustomEntityNode({ data, selected }: { data: any; selected?: boolean }) {
  const attribution = attributionOf(data);
  const tier = CERTAINTY_TIERS[tierOf(data)];
  const isVerified = Boolean(data.verified);
  const entityType = data.entity_type as string | undefined;
  const meta = getEntityTypeMeta(entityType);
  const platform = String(data.platform || meta.label);
  const icon = getFindingIcon(data.platform, entityType);

  // El estilo del nodo lo decide su tipo, no solo la confianza. Antes solo
  // `breach` y `phone` tenían tratamiento propio y los otros ocho tipos eran
  // visualmente idénticos entre sí.
  // El color del nodo sigue diciendo QUÉ es (su tipo); el halo y la insignia
  // dicen CUÁNTO se le atribuye. Los descartados se atenúan para que la maraña
  // de una investigación con cientos de resultados deje ver lo que importa.
  const nodeClass = selected
    ? "border-sky-400 ring-2 ring-sky-500/30 bg-[#162030]"
    : `${meta.node} ${tier.ring} ${tier.id === "discarded" ? "opacity-60" : ""}`;

  return (
    <div
      className={`px-3 py-2.5 rounded-lg border transition-all min-w-[170px] max-w-[220px] shadow-lg ${nodeClass}`}
      title={meta.description}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-1.5 !h-1.5" />

      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 truncate">
          {/* `createElement` en vez de `<Icon/>`: la regla react-hooks/static-components
              interpreta una variable capitalizada en JSX como un componente definido
              durante el render. Aquí `Icon` es una referencia a un icono ya existente
              que se elige por tipo/plataforma, no un componente nuevo. */}
          {createElement(icon, {
            className: `w-3.5 h-3.5 shrink-0 ${meta.accent}`,
            "aria-hidden": true,
          })}
          <span className="text-[10px] font-mono text-slate-300 uppercase tracking-wider truncate">
            {platform}
          </span>
        </div>

        <span
          title={
            `${tier.help}

Atribución (¿es del objetivo?): ` +
            `${intPercent(attribution)}
Detección (¿existe la cuenta?): ` +
            `${intPercent(Number(data.existence_confidence ?? data.confidence ?? 0))}`
          }
          className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${tier.badge}`}
        >
          {intPercent(attribution)}
        </span>
      </div>

      <div className="text-xs font-semibold text-slate-200 truncate" title={String(data.label || "")}>
        {String(data.label || "")}
      </div>

      {data.display_name && data.display_name !== data.label && (
        <div className="text-[10px] text-slate-400 truncate mt-0.5">
          {String(data.display_name)}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 mt-1">
        <span className={`text-[9px] font-mono uppercase tracking-wide ${meta.accent}`}>
          {meta.label}
        </span>
        <span className="text-[9px] font-mono text-slate-500" title={tier.help}>
          {isVerified ? "verificado" : tier.label.toLowerCase()}
        </span>
      </div>
    </div>
  );
}

function intPercent(val: number): string {
  return `${Math.round((val || 0) * 100)}%`;
}

export function DigitalMapGraph({ investigationId }: { investigationId: string }) {
  const [allNodes, setAllNodes] = useState<any[]>([]);
  const [allEdges, setAllEdges] = useState<any[]>([]);
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  // Nivel mínimo de atribución que se dibuja. Arranca en "probable" a
  // propósito: una investigación real produce cientos de homónimos descartados,
  // y mostrarlos todos de entrada convierte el mapa en una maraña donde no se
  // distingue lo que sí es de la persona.
  const [minTier, setMinTier] = useState<"all" | "probable" | "attributed">("probable");

  const nodeTypes = useMemo(
    () => ({
      personRoot: PersonRootNode,
      customEntity: CustomEntityNode,
    }),
    []
  );

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      const data: GraphResponse = await getInvestigationGraph(investigationId);
      setAllNodes(data.nodes);
      setAllEdges(data.edges);
      setNodes(data.nodes);
      setEdges(data.edges);
      setError(null);
    } catch (err: unknown) {
      // Antes esto solo hacía console.error y el usuario veía un lienzo vacío
      // sin ninguna explicación, indistinguible de una investigación sin nodos.
      setError(err instanceof Error ? err.message : "No se pudo cargar el mapa digital");
    } finally {
      setLoading(false);
    }
  }, [investigationId, setNodes, setEdges]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Apply layer filtering
  useEffect(() => {
    const passesTier = (n: { type?: string; data?: NodeCertainty }) => {
      if (n.type === "personRoot") return true;
      const tier = tierOf(n.data);
      if (minTier === "all") return true;
      if (minTier === "probable") return tier !== "discarded";
      return tier === "attributed";
    };

    if (activeCategory === "all") {
      const soloCertidumbre = allNodes.filter(passesTier);
      const idsVisibles = new Set(soloCertidumbre.map((n) => n.id));
      setNodes(soloCertidumbre);
      setEdges(
        allEdges.filter(
          (e: { source: string; target: string }) =>
            idsVisibles.has(e.source) && idsVisibles.has(e.target)
        )
      );
      return;
    }
    const filteredNodes = allNodes.filter(
      (n) =>
        (n.type === "personRoot" || n.data.entity_type === activeCategory) &&
        passesTier(n)
    );
    const visibleNodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = allEdges.filter(
      (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );

    setNodes(filteredNodes);
    setEdges(filteredEdges);
  }, [activeCategory, minTier, allNodes, allEdges, setNodes, setEdges]);

  const onNodeClick = useCallback((_: any, node: any) => {
    setSelectedNode(node);
  }, []);

  const handleExportGraphJson = () => {
    const data = { nodes: allNodes, edges: allEdges };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `graph-${investigationId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportGephiGraphml = () => {
    window.open(getGraphmlUrl(investigationId), "_blank");
  };

  // Los filtros se derivan de los tipos presentes en el grafo. La lista fija
  // anterior solo cubría 6 de los 10 tipos que el backend emite, dejando
  // `image_match`, `google_account`, `academic_profile`, `search_mention` y
  // `document` sin capa aislable.
  const categories = useMemo(
    () => buildEntityFilters(allNodes.map((n) => n.data?.entity_type)),
    [allNodes]
  );

  return (
    <div className="h-[680px] w-full panel-card relative flex flex-col overflow-hidden border border-[#1e293b]">
      {/* Top Filter Bar */}
      <div className="px-4 py-3 bg-[#0d131f] border-b border-[#212f45] flex flex-wrap items-center justify-between gap-3 z-10">
        <div className="flex items-center gap-2 overflow-x-auto">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-sky-400 bg-sky-950/40 px-2.5 py-1 rounded border border-sky-500/30 shrink-0">
            <Filter className="w-3.5 h-3.5" />
            <span>FILTRAR CAPAS:</span>
          </div>
          {categories.map((cat) => {
            const meta = getEntityTypeMeta(cat.id);
            const CatIcon = cat.id === "all" ? null : meta.Icon;
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => setActiveCategory(cat.id)}
                title={cat.description}
                aria-pressed={activeCategory === cat.id}
                className={`flex items-center gap-1.5 text-xs font-mono px-3 py-1 rounded-md transition-all whitespace-nowrap cursor-pointer border ${
                  activeCategory === cat.id
                    ? "bg-sky-500 text-white font-bold shadow-md shadow-sky-950 border-sky-400"
                    : "bg-[#151e2c] text-slate-300 hover:text-white hover:bg-[#1e2b3e] border-[#2b3a52]"
                }`}
              >
                {CatIcon && (
                  <CatIcon
                    className={`w-3.5 h-3.5 ${
                      activeCategory === cat.id ? "text-white" : meta.accent
                    }`}
                    aria-hidden="true"
                  />
                )}
                <span>{cat.label}</span>
                <span className="opacity-70">{cat.count}</span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-3">
          {/* Filtro por certeza de ATRIBUCIÓN. Es lo que hace legible el mapa:
              una investigación real produce cientos de homónimos descartados. */}
          <div
            className="flex items-center gap-1 bg-[#151e2c] rounded-md border border-[#2b3a52] p-0.5"
            role="group"
            aria-label="Filtrar por certeza de atribución"
          >
            {(
              [
                ["attributed", "Atribuidos", "Solo los que el modelo atribuye a la persona (≥70%)."],
                ["probable", "+ Probables", "Añade los de evidencia parcial (40-70%)."],
                ["all", "Todos", "Incluye los homónimos descartados. Con cientos de resultados, el mapa se vuelve una maraña."],
              ] as const
            ).map(([id, etiqueta, ayuda]) => (
              <button
                key={id}
                type="button"
                onClick={() => setMinTier(id)}
                title={ayuda}
                aria-pressed={minTier === id}
                className={`text-[11px] font-mono px-2 py-0.5 rounded transition-colors cursor-pointer ${
                  minTier === id
                    ? "bg-sky-500 text-white font-bold"
                    : "text-slate-300 hover:text-white hover:bg-[#1e2b3e]"
                }`}
              >
                {etiqueta}
              </button>
            ))}
          </div>

          <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-950/40 px-2.5 py-1 rounded border border-emerald-500/30">
            {nodes.length} nodos activos
          </span>
          <button
            onClick={handleExportGraphJson}
            title="Exportar topología de grafo en JSON"
            className="text-xs font-mono px-3 py-1 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 border border-[#2b3a52] transition-colors cursor-pointer"
          >
            Grafo (JSON)
          </button>
          <button
            onClick={handleExportGephiGraphml}
            title="Descargar archivo .graphml para abrir en Gephi, Cytoscape o NetworkX"
            className="text-xs font-mono px-3 py-1 rounded-md bg-purple-950/60 hover:bg-purple-900/70 text-purple-200 border border-purple-500/40 transition-colors cursor-pointer"
          >
            Gephi (.graphml)
          </button>
        </div>
      </div>

      {/* Fila: lienzo + panel lateral de detalle.
          El panel usa `w-80 border-l shrink-0`, estilos de barra lateral que solo
          funcionan dentro de un contenedor en fila. Antes era hijo directo del
          contenedor `flex-col` raíz, así que se apilaba debajo del lienzo y
          quedaba recortado por el `overflow-hidden` de altura fija. */}
      <div className="flex-1 flex min-h-0">
      {/* React Flow Canvas */}
      <div className="flex-1 h-full relative min-w-0">
        {loading ? (
          <div
            role="status"
            className="absolute inset-0 flex items-center justify-center bg-[#0b0f17]/80 z-20 text-xs font-mono text-slate-300"
          >
            <span
              className="w-4 h-4 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mr-2"
              aria-hidden="true"
            />
            Construyendo mapa de relaciones...
          </div>
        ) : null}

        {!loading && error ? (
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
        ) : null}

        {!loading && !error && nodes.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#0b0f17]/90 z-20 px-6 text-center">
            <p className="text-xs font-mono text-slate-300">
              No hay nodos que mostrar en esta capa.
            </p>
            <p className="text-[11px] text-slate-400 mt-1">
              Prueba con otro filtro o espera a que el motor termine la extracción.
            </p>
          </div>
        ) : null}

        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={1.5}
        >
          <Background color="#1e293b" gap={20} size={1} />
          <Controls className="!bg-[#121824] !border-[#212d40] !text-slate-200" />
          <MiniMap
            className="!bg-[#0d121c] !border-[#1e293b] rounded-md"
            nodeColor={(n) => (n.type === "personRoot" ? "#38bdf8" : "#334155")}
          />
        </ReactFlow>
      </div>

      {/* Detail Slideout for Clicked Entity */}
      {selectedNode && (
        <aside
          aria-label="Detalle de la entidad seleccionada"
          className="w-72 lg:w-80 border-l border-[#1e293b] bg-[#0e131d] p-4 overflow-y-auto shrink-0"
        >
          <div className="flex items-center justify-between pb-3 border-b border-[#1e293b] mb-4">
            <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
              Detalle de Entidad
            </h4>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-xs font-mono text-slate-500 hover:text-slate-300"
            >
              Cerrar ✕
            </button>
          </div>

          <div className="space-y-3 text-xs">
            <div>
              <span className="text-[10px] font-mono text-slate-500 uppercase block">Tipo y Plataforma</span>
              <span className="font-semibold text-slate-200">
                {selectedNode.data.platform || selectedNode.data.entity_type}
              </span>
            </div>

            <div>
              <span className="text-[10px] font-mono text-slate-500 uppercase block">Valor / Enlace</span>
              {selectedNode.data.value?.startsWith("http") ? (
                <a
                  href={selectedNode.data.value}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-400 hover:underline flex items-center gap-1 break-all mt-0.5"
                >
                  <span className="truncate">{selectedNode.data.value}</span>
                  <ExternalLink className="w-3 h-3 shrink-0" />
                </a>
              ) : (
                <span className="font-mono text-slate-300 break-all">{selectedNode.data.value}</span>
              )}
            </div>

            <div className="pt-3 border-t border-[#1e293b]">
              <span className="text-[10px] font-mono text-slate-400 uppercase block mb-2">
                ¿Por qué creemos que es esta persona?
              </span>
              <IdentityEvidence
                breakdown={selectedNode.data.metadata_info?.identity_breakdown}
                identityScore={selectedNode.data.metadata_info?.identity_score}
                existenceConfidence={selectedNode.data.existence_confidence}
                finalConfidence={Number(selectedNode.data.confidence || 0)}
              />
            </div>

            {selectedNode.data.metadata_info?.bio && (
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Biografía / Snippet</span>
                <p className="text-slate-300 text-[11px] mt-0.5 bg-[#141b28] p-2 rounded border border-[#1e293b]">
                  {selectedNode.data.metadata_info.bio}
                </p>
              </div>
            )}

            {selectedNode.data.metadata_info?.extracted_emails?.length > 0 && (
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Correos Extraídos</span>
                <ul className="list-disc list-inside text-sky-400 text-[11px] mt-0.5">
                  {selectedNode.data.metadata_info.extracted_emails.map((em: string) => (
                    <li key={em}>{em}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </aside>
      )}
      </div>
    </div>
  );
}
