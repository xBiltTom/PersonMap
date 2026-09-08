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
import { CERTAINTY_BANDS, DEFAULT_VISIBLE_BANDS, bandOf } from "@/lib/certainty";
import { IdentityEvidence } from "@/components/identity/IdentityEvidence";
import { PlainExplanation } from "@/components/identity/PlainExplanation";
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
/** Lo mínimo que hace falta leer de un nodo para decidir su certeza. */
interface NodeCertainty {
  identity_score?: number | null;
  confidence?: number | null;
  existence_confidence?: number | null;
  verified?: boolean;
  metadata_info?: {
    identity_score?: number;
    identity_breakdown?: { signals_evaluated?: number };
  };
}

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
function attributionOf(data: NodeCertainty | undefined): number {
  const score = data?.identity_score ?? data?.metadata_info?.identity_score;
  if (typeof score === "number") return score;
  // Entidades anteriores a la separación de métricas.
  return Number(data?.confidence || 0);
}

function bandOfNode(data: NodeCertainty | undefined) {
  return bandOf(
    attributionOf(data),
    Boolean(data?.verified),
    data?.metadata_info?.identity_breakdown?.signals_evaluated
  );
}

function CustomEntityNode({ data, selected }: { data: any; selected?: boolean }) {
  const attribution = attributionOf(data);
  const band = bandOfNode(data);
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
    : `${meta.node} ${band.ring} ${band.dim ? "opacity-55" : ""}`;

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
            `${band.label}: ${band.help}

Atribución (¿es del objetivo?): ` +
            `${intPercent(attribution)}
Detección (¿existe la cuenta?): ` +
            `${intPercent(Number(data.existence_confidence ?? data.confidence ?? 0))}`
          }
          className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${band.badge}`}
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
        <span className="text-[9px] font-mono text-slate-500" title={band.help}>
          {band.label.toLowerCase()}
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
  // Bandas de certeza que el usuario ha elegido. `null` = no ha tocado el
  // filtro y manda el criterio automático de abajo.
  const [userBands, setUserBands] = useState<Set<string> | null>(null);

  /**
   * Bandas realmente visibles.
   *
   * Por defecto se ocultan las dos de abajo: una investigación con muchos
   * resultados produce cientos de homónimos y mostrarlos de entrada convierte
   * el mapa en una maraña.
   *
   * **Pero nunca a costa de dejar el mapa vacío.** Una persona con huella
   * modesta —el caso típico de un estudiante, que es el público de esta
   * herramienta— puede tener todos sus hallazgos en las bandas bajas, y
   * entonces el filtro por defecto escondía absolutamente todo y solo quedaba
   * el nodo raíz. Pasó con una búsqueda real: 17 hallazgos, ninguno visible.
   */
  const visibleBands = useMemo(() => {
    if (userBands) return userBands;

    const porDefecto = new Set(DEFAULT_VISIBLE_BANDS);
    const hayAlguno = allNodes.some(
      (n) => n.type !== "personRoot" && porDefecto.has(bandOfNode(n.data).id)
    );
    return hayAlguno ? porDefecto : new Set(CERTAINTY_BANDS.map((b) => b.id));
  }, [userBands, allNodes]);

  /**
   * Cuántos hallazgos alcanzaron al menos "Probable".
   *
   * Si son cero, el mapa se ve raro y hay que decir por qué: no es que la
   * herramienta no haya encontrado nada, es que no pudo atribuir nada. Son
   * cosas distintas y callarlo deja al usuario pensando que falló el sistema.
   */
  const atribuibles = useMemo(
    () =>
      allNodes.filter(
        (n) =>
          n.type !== "personRoot" &&
          !bandOfNode(n.data).dim &&
          bandOfNode(n.data).id !== "verified"
      ).length,
    [allNodes]
  );
  const totalHallazgos = useMemo(
    () => allNodes.filter((n) => n.type !== "personRoot").length,
    [allNodes]
  );

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
    const passesTier = (n: { type?: string; data?: NodeCertainty }) =>
      n.type === "personRoot" || visibleBands.has(bandOfNode(n.data).id);

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
  }, [activeCategory, visibleBands, allNodes, allEdges, setNodes, setEdges]);

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
          {/* Filtro por banda de certeza de ATRIBUCIÓN. Es lo que hace legible
              el mapa: una investigación real produce cientos de homónimos
              descartados. Las bandas salen de `lib/certainty`, la misma fuente
              que usan el nodo y la explicación, para que no se contradigan. */}
          <div
            className="flex items-center gap-1 flex-wrap"
            role="group"
            aria-label="Filtrar por certeza de atribución"
          >
            {CERTAINTY_BANDS.map((banda) => {
              const activa = visibleBands.has(banda.id);
              const cuantos = allNodes.filter(
                (n) => n.type !== "personRoot" && bandOfNode(n.data).id === banda.id
              ).length;

              return (
                <button
                  key={banda.id}
                  type="button"
                  onClick={() =>
                    setUserBands(() => {
                      const next = new Set(visibleBands);
                      if (next.has(banda.id)) next.delete(banda.id);
                      else next.add(banda.id);
                      return next;
                    })
                  }
                  title={banda.help}
                  aria-pressed={activa}
                  disabled={cuantos === 0}
                  className={`flex items-center gap-1.5 text-[11px] font-mono px-2 py-1 rounded border transition-colors whitespace-nowrap cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed ${
                    activa
                      ? `${banda.chipActive} font-bold`
                      : "bg-[#151e2c] text-slate-400 border-[#2b3a52] hover:text-slate-200"
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${activa ? "bg-white/80" : banda.dot}`}
                    aria-hidden="true"
                  />
                  <span>{banda.label}</span>
                  <span className="opacity-70">{cuantos}</span>
                </button>
              );
            })}
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

        {!loading && !error && totalHallazgos > 0 && atribuibles === 0 && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 max-w-xl px-4 py-2.5 rounded-md bg-[#1a1408] border border-amber-500/40 shadow-lg">
            <p className="text-[11px] text-amber-200 font-semibold">
              Se encontraron {totalHallazgos} hallazgos, pero ninguno se pudo
              atribuir con seguridad.
            </p>
            <p className="text-[11px] text-slate-300 mt-1 leading-snug">
              No es que no haya huella: es que no hay <strong>datos en común</strong>{" "}
              suficientes para demostrar que esas cuentas son tuyas. Con solo un
              nombre y un correo, la mayoría de perfiles no ofrecen nada que
              comparar. Añadir tu alias habitual o tu universidad al buscar suele
              cambiar el resultado por completo.
            </p>
          </div>
        )}

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
                ¿Por qué este porcentaje?
              </span>

              {/* Primero la explicación en castellano llano, que es lo que
                  necesita la persona a la que se le enseña su expediente; el
                  desglose técnico queda debajo, plegado, para quien lo audite. */}
              <PlainExplanation
                breakdown={selectedNode.data.metadata_info?.identity_breakdown}
                score={attributionOf(selectedNode.data)}
                verified={Boolean(selectedNode.data.verified)}
              />

              <details className="mt-3 group">
                <summary className="text-[10px] font-mono text-slate-500 hover:text-slate-300 cursor-pointer select-none">
                  Ver el desglose técnico del modelo
                </summary>
                <div className="mt-2">
              <IdentityEvidence
                breakdown={selectedNode.data.metadata_info?.identity_breakdown}
                identityScore={selectedNode.data.metadata_info?.identity_score}
                existenceConfidence={selectedNode.data.existence_confidence}
                finalConfidence={Number(selectedNode.data.confidence || 0)}
              />
                </div>
              </details>
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
