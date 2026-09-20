"use client";

import { Fragment, useMemo, useState } from "react";
import { CalendarDays, ChevronDown, ExternalLink, Eye, Map as MapIcon, Network, Search } from "lucide-react";
import { EntityInspector } from "@/components/graph/EntityInspector";
import { PlatformIcon, getEntityTheme } from "@/components/graph/PlatformIcon";
import {
  buildEntityInspectorViewModel,
  buildRelationshipEvidenceFields,
  entityToGraphNode,
  getInspectorEvidenceBadges,
  getInspectorSearchText,
  type EntityInspectorViewModel,
} from "@/lib/entityInspector";
import { buildEntityFilters, getEntityTypeMeta } from "@/lib/entityTypes";
import { getFriendlyRelationLabel, isProvenanceEdge } from "@/lib/graphSemantics";
import { LAYER_META } from "@/lib/engines";
import type { EntityData, GraphEdge, GraphNode, GraphResponse } from "@/lib/types";

const PAGE_SIZE = 20;

interface FindingsTableProps {
  entities: EntityData[];
  /** Misma respuesta que usa el mapa; null mientras la página la recupera. */
  graph?: GraphResponse | null;
  onViewInMap?: (entityId: string) => void;
}

function formatDate(value?: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return undefined;
  return new Intl.DateTimeFormat("es-PE", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function relationshipEdgesFor(nodeId: string, edges: GraphEdge[]): GraphEdge[] {
  return edges.filter((edge) => !isProvenanceEdge(edge) && (edge.source === nodeId || edge.target === nodeId));
}

function relatedNode(edge: GraphEdge, nodeId: string, nodesById: Map<string, GraphNode>): GraphNode | undefined {
  return nodesById.get(edge.source === nodeId ? edge.target : edge.source);
}

function EvidenceChips({ view }: { view: EntityInspectorViewModel }) {
  const badges = getInspectorEvidenceBadges(view);
  if (!badges.length) return <span className="font-mono text-[10px] text-slate-500">Sin datos adicionales</span>;
  return (
    <div className="flex max-w-[240px] flex-wrap gap-1">
      {badges.slice(0, 4).map((badge) => (
        <span
          key={badge.key}
          className="rounded border border-sky-500/20 bg-sky-500/[0.08] px-1.5 py-0.5 font-mono text-[9px] text-sky-200"
        >
          {badge.label}
        </span>
      ))}
      {badges.length > 4 && (
        <span className="rounded border border-slate-700 bg-slate-800/60 px-1 py-0.5 font-mono text-[9px] text-slate-400">
          +{badges.length - 4}
        </span>
      )}
    </div>
  );
}

function ProvenanceCell({ item, view }: { item: EntityData; view: EntityInspectorViewModel }) {
  const layers = item.metadata_info?.engine_layers ?? [];
  const discoveredAt = formatDate(view.provenance?.discoveredAt);
  return (
    <div className="min-w-[130px] font-mono text-[10px] leading-relaxed text-slate-400">
      <div className="font-medium text-slate-200">{view.provenance?.sourceTool ?? item.source_tool}</div>
      {item.metadata_info?.catalog_source && (
        <div className="text-[9px] text-slate-400">
          {item.metadata_info.catalog_source}
          {item.metadata_info.catalog_enriched_by ? " + maigret" : ""}
        </div>
      )}
      {layers.length > 0 && (
        <div className="mt-1 flex gap-1">
          {layers.map((layer) => {
            const layerMeta = LAYER_META[layer];
            return layerMeta ? (
              <span
                key={layer}
                title={layerMeta.description}
                className={`rounded border px-1 py-px text-[9px] font-bold ${layerMeta.badge}`}
              >
                {layerMeta.short}
              </span>
            ) : null;
          })}
        </div>
      )}
      {discoveredAt && (
        <div className="mt-1 flex items-center gap-1 text-[9px] text-slate-400">
          <CalendarDays className="h-2.5 w-2.5" />
          {discoveredAt}
        </div>
      )}
    </div>
  );
}

function RelationSummary({
  edges,
  graphLoaded,
  isOpen,
  onToggle,
}: {
  edges: GraphEdge[];
  graphLoaded: boolean;
  isOpen: boolean;
  onToggle: () => void;
}) {
  if (!graphLoaded) return <span className="font-mono text-[10px] text-slate-500">Consultando…</span>;
  if (!edges.length) return <span className="font-mono text-[10px] text-slate-500">Sin relaciones</span>;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={isOpen}
      className="inline-flex items-center gap-1 rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1 font-mono text-[10px] text-violet-200 transition-colors hover:bg-violet-500/20"
    >
      <Network className="h-3 w-3" />
      <span>
        {edges.length} {edges.length === 1 ? "relación" : "relaciones"}
      </span>
      <ChevronDown className={`h-3 w-3 transition-transform ${isOpen ? "rotate-180" : ""}`} />
    </button>
  );
}

function RelationshipRows({
  item,
  node,
  edges,
  nodesById,
  onViewInMap,
}: {
  item: EntityData;
  node: GraphNode;
  edges: GraphEdge[];
  nodesById: Map<string, GraphNode>;
  onViewInMap?: (entityId: string) => void;
}) {
  return (
    <tr className="bg-[#09111c]">
      <td colSpan={5} className="px-4 py-3">
        <div className="max-w-3xl rounded-lg border border-[#1e2f45] bg-[#070e18]/90 p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-violet-300 font-semibold">
              Relaciones documentadas en el grafo
            </p>
            {onViewInMap && (
              <button
                type="button"
                onClick={() => onViewInMap(item.id)}
                className="inline-flex items-center gap-1 font-mono text-[10px] text-cyan-300 hover:text-cyan-200"
              >
                <MapIcon className="h-3 w-3" /> Ver en mapa
              </button>
            )}
          </div>
          <div className="divide-y divide-[#17273a]">
            {edges.map((edge) => {
              const counterpart = relatedNode(edge, node.id, nodesById);
              const fields = buildRelationshipEvidenceFields(edge.evidence);
              return (
                <div key={edge.id} className="py-2 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                    <span className="font-medium text-slate-200">{node.data.label}</span>
                    <span className="text-slate-500">↔</span>
                    <span className="font-medium text-slate-200">
                      {counterpart?.data.label ?? "Hallazgo relacionado"}
                    </span>
                    <span className="rounded border border-violet-500/30 bg-violet-500/15 px-1.5 py-0.2 font-mono text-[9px] text-violet-200">
                      {getFriendlyRelationLabel(edge.relation_type, edge.label)}
                    </span>
                  </div>
                  {fields.length > 0 && (
                    <p className="mt-1 font-mono text-[10px] text-slate-400">
                      {fields
                        .slice(0, 2)
                        .map((f) => `${f.label}: ${f.value}`)
                        .join(" · ")}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </td>
    </tr>
  );
}

export function FindingsTable({ entities, graph = null, onViewInMap }: FindingsTableProps) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [openRelationsId, setOpenRelationsId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const fallbackNodes = useMemo(() => entities.map(entityToGraphNode), [entities]);
  const nodes = graph?.nodes ?? fallbackNodes;
  const evidenceEdges = useMemo(
    () => (graph?.edges ?? []).filter((edge) => !isProvenanceEdge(edge)),
    [graph]
  );
  const nodesById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const nodeForEntity = useMemo(
    () =>
      new Map(
        entities.map((entity) => [
          entity.id,
          nodesById.get(`ent-${entity.id}`) ?? entityToGraphNode(entity),
        ])
      ),
    [entities, nodesById]
  );
  const viewsByEntity = useMemo(
    () =>
      new Map(
        entities.map((entity) => {
          const node = nodeForEntity.get(entity.id) ?? entityToGraphNode(entity);
          return [
            entity.id,
            buildEntityInspectorViewModel(node, nodes, evidenceEdges, (edge) =>
              getFriendlyRelationLabel(edge.relation_type, edge.label)
            ),
          ];
        })
      ),
    [entities, evidenceEdges, nodeForEntity, nodes]
  );

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return entities.filter((entity) => {
      const node = nodeForEntity.get(entity.id) ?? entityToGraphNode(entity);
      return (
        (!needle || getInspectorSearchText(node).includes(needle)) &&
        (filterType === "all" || entity.entity_type === filterType)
      );
    });
  }, [entities, filterType, nodeForEntity, search]);

  const categories = useMemo(
    () => buildEntityFilters(entities.map((entity) => entity.entity_type)),
    [entities]
  );
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const visible = useMemo(
    () => filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [currentPage, filtered]
  );

  const selectedNode = selectedNodeId ? nodesById.get(selectedNodeId) : undefined;

  return (
    <div className="relative">
      <div className="overflow-hidden rounded-xl border border-[#1a2c42] bg-[#0c1420] shadow-xl">
        {/* Search & Category Filter Toolbar */}
        <div className="flex flex-col justify-between gap-3 border-b border-[#1b2b3e] bg-[#08101c]/80 p-3.5 md:flex-row md:items-center">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              type="search"
              placeholder="Buscar por valor o plataforma…"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(0);
              }}
              className="w-64 rounded-lg border border-[#1e2f45] bg-[#070e18] py-1.5 pl-8 pr-3 font-mono text-xs text-slate-200 placeholder-slate-500 focus:border-sky-400 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
            {categories.map((category) => (
              <button
                key={category.id}
                type="button"
                onClick={() => {
                  setFilterType(category.id);
                  setPage(0);
                }}
                title={category.description}
                aria-pressed={filterType === category.id}
                className={`whitespace-nowrap rounded-md border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                  filterType === category.id
                    ? "border-sky-500/40 bg-sky-500/20 font-semibold text-sky-300"
                    : "border-[#1e2f45] bg-[#0d1624] text-slate-400 hover:text-slate-200"
                }`}
              >
                {category.label}
                <span className="ml-1.5 opacity-70">({category.count})</span>
              </button>
            ))}
          </div>
        </div>

        {/* Forensic Findings Table */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-xs">
            <thead className="border-b border-[#1b2b3e] bg-[#08101c] font-mono text-[10px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">Hallazgo / Plataforma</th>
                <th className="px-4 py-3">Evidencia extraída</th>
                <th className="px-4 py-3">Relaciones</th>
                <th className="px-4 py-3">Procedencia</th>
                <th className="px-4 py-3 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#142234]">
              {!filtered.length ? (
                <tr>
                  <td colSpan={5} className="py-10 text-center font-mono text-slate-500">
                    No se encontraron hallazgos con los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                visible.map((item) => {
                  const node = nodeForEntity.get(item.id) ?? entityToGraphNode(item);
                  const view = viewsByEntity.get(item.id) as EntityInspectorViewModel;
                  const meta = getEntityTypeMeta(item.entity_type);
                  const theme = getEntityTheme(item.platform, item.entity_type, item.value);
                  const relationships = relationshipEdgesFor(node.id, evidenceEdges);
                  const relationsOpen = openRelationsId === item.id;
                  const displayIdentifier = item.display_name || view.subtitle || item.value;

                  return (
                    <Fragment key={item.id}>
                      <tr className="transition-colors hover:bg-[#101a28]">
                        <td className="min-w-[260px] px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <div
                              className={`flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-[#070e18] ${theme.borderClass}`}
                              title={item.platform || meta.label}
                            >
                              <PlatformIcon
                                platform={item.platform}
                                entityType={item.entity_type}
                                value={item.value}
                                displayName={item.display_name}
                                avatarUrl={item.metadata_info?.avatar_url}
                                className={`h-4 w-4 ${theme.accentText}`}
                              />
                            </div>
                            <div className="min-w-0">
                              <div className="font-medium text-slate-200">
                                {view.platform ?? meta.label}
                                <span className="mx-1 text-slate-600">·</span>
                                <span className="font-mono text-[10px] text-slate-400">
                                  {view.entityType}
                                </span>
                              </div>
                              <div className="mt-0.5 truncate font-mono text-[11px] text-slate-300">
                                {displayIdentifier}
                              </div>
                              {view.primaryLink && (
                                <a
                                  href={view.primaryLink.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="mt-0.5 flex max-w-[240px] items-center gap-1 truncate font-mono text-[9px] text-sky-400/80 hover:text-sky-300"
                                >
                                  <span className="truncate">
                                    {view.primaryLink.url.replace(/^https?:\/\//, "")}
                                  </span>
                                  <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                                </a>
                              )}
                            </div>
                          </div>
                        </td>

                        <td className="px-4 py-3">
                          <EvidenceChips view={view} />
                        </td>

                        <td className="px-4 py-3">
                          <RelationSummary
                            edges={relationships}
                            graphLoaded={graph !== null}
                            isOpen={relationsOpen}
                            onToggle={() =>
                              setOpenRelationsId(relationsOpen ? null : item.id)
                            }
                          />
                        </td>

                        <td className="px-4 py-3">
                          <ProvenanceCell item={item} view={view} />
                        </td>

                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setSelectedNodeId(node.id)}
                              title="Inspeccionar entidad forense"
                              aria-label="Inspeccionar entidad forense"
                              className="rounded p-1.5 text-slate-400 transition-colors hover:bg-sky-500/10 hover:text-sky-300"
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </button>
                            {view.primaryLink && (
                              <a
                                href={view.primaryLink.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Abrir recurso original"
                                aria-label="Abrir recurso original"
                                className="rounded p-1.5 text-slate-400 transition-colors hover:bg-sky-500/10 hover:text-sky-300"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            )}
                            {onViewInMap && (
                              <button
                                type="button"
                                onClick={() => onViewInMap(item.id)}
                                title="Localizar en el mapa digital"
                                aria-label="Localizar en el mapa digital"
                                className="rounded p-1.5 text-slate-400 transition-colors hover:bg-violet-500/10 hover:text-violet-300"
                              >
                                <MapIcon className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {relationsOpen && (
                        <RelationshipRows
                          item={item}
                          node={node}
                          edges={relationships}
                          nodesById={nodesById}
                          onViewInMap={onViewInMap}
                        />
                      )}
                    </Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        {filtered.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#1b2b3e] bg-[#08101c] px-4 py-3 font-mono text-[11px]">
            <span className="text-slate-400">
              Mostrando{" "}
              <span className="text-slate-200">
                {currentPage * PAGE_SIZE + 1}-
                {Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)}
              </span>{" "}
              de <span className="text-slate-200">{filtered.length}</span> hallazgos
              {filtered.length !== entities.length && (
                <span className="text-slate-500"> (de {entities.length} totales)</span>
              )}
            </span>
            {totalPages > 1 && (
              <nav className="flex items-center gap-2" aria-label="Paginación de hallazgos">
                <button
                  type="button"
                  onClick={() => setPage((value) => Math.max(0, value - 1))}
                  disabled={currentPage === 0}
                  className="rounded border border-[#1e2f45] bg-[#0c1420] px-2.5 py-1 text-slate-300 transition-colors hover:bg-[#131f30] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Anterior
                </button>
                <span className="text-slate-400">
                  Página {currentPage + 1} de {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((value) => Math.min(totalPages - 1, value + 1))}
                  disabled={currentPage >= totalPages - 1}
                  className="rounded border border-[#1e2f45] bg-[#0c1420] px-2.5 py-1 text-slate-300 transition-colors hover:bg-[#131f30] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Siguiente
                </button>
              </nav>
            )}
          </div>
        )}
      </div>

      {/* Modal Inspector when opened from table */}
      {selectedNode && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 p-3 sm:p-4 backdrop-blur-sm animate-fade-in"
          onClick={() => setSelectedNodeId(null)}
        >
          <div
            className="relative h-full max-h-[92vh] w-full max-w-[420px]"
            onClick={(e) => e.stopPropagation()}
          >
            <EntityInspector
              node={selectedNode}
              nodes={nodes}
              edges={evidenceEdges}
              onClose={() => setSelectedNodeId(null)}
              onSelectNode={setSelectedNodeId}
              relationLabel={(edge) => getFriendlyRelationLabel(edge.relation_type, edge.label)}
              containerMode="embedded"
            />
          </div>
        </div>
      )}
    </div>
  );
}
