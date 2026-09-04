"use client";

import { Fragment, useState, useMemo } from "react";
import { EntityData } from "@/lib/types";
import { Search, ExternalLink, CheckCircle, ChevronDown, Clock } from "lucide-react";
import {
  buildEntityFilters,
  getEntityTypeMeta,
  getFindingIcon,
} from "@/lib/entityTypes";
import { IdentityEvidence } from "@/components/identity/IdentityEvidence";
import { LAYER_META } from "@/lib/engines";

export function FindingsTable({ entities }: { entities: EntityData[] }) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const filtered = useMemo(() => {
    const needle = search.toLowerCase();
    return entities.filter((e) => {
      const matchSearch =
        (e.display_name || "").toLowerCase().includes(needle) ||
        (e.value || "").toLowerCase().includes(needle) ||
        (e.platform || "").toLowerCase().includes(needle);

      // Antes había dos ramas muertas aquí: `filterType === "social"` (id que no
      // existía en la lista de categorías) y una comparación de "academic"
      // redundante con la igualdad de la línea anterior.
      const matchType = filterType === "all" || e.entity_type === filterType;

      return matchSearch && matchType;
    });
  }, [entities, search, filterType]);

  // Los filtros se derivan de los tipos realmente presentes, así que un
  // `entity_type` nuevo del backend aparece solo y no quedan categorías vacías.
  const categories = useMemo(
    () => buildEntityFilters(entities.map((e) => e.entity_type)),
    [entities]
  );

  return (
    <div className="panel-card overflow-hidden">
      {/* Table Header Bar */}
      <div className="p-4 border-b border-[#1e293b] flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Buscar en hallazgos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-[#0b0f17] border border-[#1e293b] rounded-md pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 w-56 font-mono"
            />
          </div>
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
          {categories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => setFilterType(cat.id)}
              title={cat.description}
              aria-pressed={filterType === cat.id}
              className={`text-[11px] font-mono px-2.5 py-1 rounded transition-colors whitespace-nowrap cursor-pointer border ${
                filterType === cat.id
                  ? "bg-sky-500/20 text-sky-300 border-sky-500/40 font-semibold"
                  : "bg-[#131b26] text-slate-300 hover:text-slate-100 border-[#233044]"
              }`}
            >
              {cat.label}
              <span className="ml-1.5 opacity-70">{cat.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#0c111a] text-[10px] font-mono uppercase tracking-wider text-slate-400 border-b border-[#1e293b]">
            <tr>
              <th className="py-3 px-4">Plataforma / Tipo</th>
              <th className="py-3 px-4">Identificador / Enlace</th>
              <th className="py-3 px-4">Herramienta Fuente</th>
              <th className="py-3 px-4 text-center">Certeza</th>
              <th className="py-3 px-4 text-right">Estado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#182334]">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-slate-500 font-mono">
                  No se encontraron hallazgos con los filtros seleccionados.
                </td>
              </tr>
            ) : (
              filtered.map((item) => {
                const meta = getEntityTypeMeta(item.entity_type);
                const Icon = getFindingIcon(item.platform, item.entity_type);
                return (
                <Fragment key={item.id}>
                <tr className="hover:bg-[#151e2c] transition-colors">
                  <td className="py-3 px-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Icon className={`w-4 h-4 shrink-0 ${meta.accent}`} aria-hidden="true" />
                      <div>
                        <div className="font-semibold text-slate-200">
                          {item.platform || meta.label}
                        </div>
                        <span
                          title={meta.description}
                          className={`inline-block mt-0.5 text-[10px] font-mono px-1.5 py-0.5 rounded border ${meta.badge}`}
                        >
                          {meta.label}
                        </span>
                      </div>
                    </div>
                  </td>

                  <td className="py-3 px-4 min-w-[240px]">
                    <div className="text-slate-200 font-medium">
                      {item.display_name || item.value}
                    </div>
                    {item.value.startsWith("http") && (
                      <a
                        href={item.value}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sky-400/80 hover:text-sky-300 text-[11px] flex items-center gap-1 mt-0.5"
                      >
                        <span className="truncate max-w-xs">{item.value}</span>
                        <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                      </a>
                    )}
                    {item.metadata_info?.bio && (
                      <p className="text-[10px] text-slate-400 mt-1 line-clamp-1 italic">
                        &quot;{item.metadata_info.bio}&quot;
                      </p>
                    )}
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap font-mono text-slate-400 text-[11px]">
                    <div>{item.source_tool}</div>

                    {/* Capa del motor híbrido que lo descubrió. Sin esto, el
                        refinamiento por IA sería una capacidad invisible: el
                        expediente no distinguiría un hallazgo del barrido
                        determinista de uno que solo existe porque lo pidió el LLM. */}
                    {item.metadata_info?.engine_layers?.length ? (
                      <div className="flex items-center gap-1 mt-1">
                        {item.metadata_info.engine_layers.map((layer) => {
                          const meta = LAYER_META[layer];
                          if (!meta) return null;
                          return (
                            <span
                              key={layer}
                              title={meta.description}
                              className={`text-[9px] font-bold px-1 py-px rounded border ${meta.badge}`}
                            >
                              {meta.short}
                            </span>
                          );
                        })}
                      </div>
                    ) : null}
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap text-center">
                    <button
                      type="button"
                      onClick={() => toggleExpanded(item.id)}
                      aria-expanded={expanded.has(item.id)}
                      title="Ver por qué se atribuye este hallazgo al objetivo"
                      className={`inline-flex items-center gap-1 font-mono text-[11px] font-bold px-2 py-0.5 rounded cursor-pointer transition-colors ${
                        item.confidence >= 0.70
                          ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                          : item.confidence >= 0.40
                          ? "bg-sky-500/10 text-sky-400 hover:bg-sky-500/20"
                          : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                      }`}
                    >
                      {Math.round(item.confidence * 100)}%
                      <ChevronDown
                        className={`w-3 h-3 transition-transform ${
                          expanded.has(item.id) ? "rotate-180" : ""
                        }`}
                        aria-hidden="true"
                      />
                    </button>
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap text-right">
                    {item.verified ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono text-emerald-400">
                        <CheckCircle className="w-3 h-3" aria-hidden="true" /> Verificado
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-400">
                        <Clock className="w-3 h-3" aria-hidden="true" /> Pendiente
                      </span>
                    )}
                  </td>
                </tr>
                {expanded.has(item.id) && (
                  <tr key={`${item.id}-evidence`} className="bg-[#0d131f]">
                    <td colSpan={5} className="px-4 py-4">
                      <div className="max-w-2xl">
                        <div className="text-[10px] font-mono text-slate-400 uppercase mb-2">
                          ¿Por qué creemos que es esta persona?
                        </div>
                        <IdentityEvidence
                          breakdown={item.metadata_info?.identity_breakdown}
                          identityScore={item.identity_score}
                          existenceConfidence={item.existence_confidence}
                          finalConfidence={item.confidence}
                          arbitration={item.metadata_info?.llm_arbitration}
                        />
                      </div>
                    </td>
                  </tr>
                )}
                </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
