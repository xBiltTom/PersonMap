"use client";

import { Fragment, useState, useMemo } from "react";
import { EntityData } from "@/lib/types";
import { Search, ExternalLink, ChevronDown, Clock } from "lucide-react";
import {
  buildEntityFilters,
  getEntityTypeMeta,
  getFindingIcon,
} from "@/lib/entityTypes";
import { AvatarThumb } from "@/components/identity/AvatarThumb";
import { LAYER_META } from "@/lib/engines";

/** Filas por página. Suficiente para desplazarse sin ahogar al navegador. */
const PAGE_SIZE = 50;

export function FindingsTable({ entities }: { entities: EntityData[] }) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);

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

  // Paginación. Antes se renderizaban todas las filas de golpe, y con el
  // catálogo ampliado a 3.400 sitios una sola investigación pasa de decenas a
  // varios cientos de hallazgos: el navegador se atasca justo al abrir la
  // pestaña delante del jurado.
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const visible = useMemo(
    () => filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [filtered, currentPage]
  );

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
              placeholder="Buscar por usuario o plataforma..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                // Volver al principio: quedarse en la página 7 de un resultado
                // que ahora tiene 2 mostraría una tabla vacía sin explicación.
                setPage(0);
              }}
              className="bg-[#0b0f17] border border-[#1e293b] rounded-md pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 w-56 font-mono"
            />
          </div>
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0">
          {categories.map((cat) => (
            <button
              key={cat.id}
              type="button"
              onClick={() => {
                setFilterType(cat.id);
                setPage(0);
              }}
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
              <th className="py-3 px-4 text-center">Indicios / Correlación</th>
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
              visible.map((item) => {
                const meta = getEntityTypeMeta(item.entity_type);
                const Icon = getFindingIcon(item.platform, item.entity_type);
                return (
                <Fragment key={item.id}>
                <tr className="hover:bg-[#151e2c] transition-colors">
                  <td className="py-3 px-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      {/* La miniatura del avatar. Hasta ahora la correlación
                          visual ocurría y movía la puntuación, pero el usuario
                          nunca veía las imágenes: es la evidencia más
                          persuasiva del sistema y estaba oculta. */}
                      {item.metadata_info?.avatar_url ? (
                        <AvatarThumb
                          url={item.metadata_info.avatar_url}
                          distance={item.metadata_info.avatar_hamming_distance}
                          source={item.metadata_info.avatar_source}
                        />
                      ) : (
                        <Icon className={`w-4 h-4 shrink-0 ${meta.accent}`} aria-hidden="true" />
                      )}
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
                    {/* Catálogo del que salió la comprobación. Es lo que
                        permite decir en el expediente de dónde vino el dato, y
                        medir en el artículo qué aportó cada dataset. */}
                    {item.metadata_info?.catalog_source && (
                      <div
                        className="text-[9px] text-slate-500 mt-0.5"
                        title={
                          item.metadata_info.catalog_enriched_by
                            ? "Sitio del catálogo curado de WhatsMyName, enriquecido con los metadatos de Maigret (formato de alias, ranking, cadenas de ausencia)."
                            : "Catálogo del que procede la comprobación de esta plataforma."
                        }
                      >
                        {item.metadata_info.catalog_source === "maigret"
                          ? "maigret"
                          : "whatsmyname"}
                        {item.metadata_info.catalog_enriched_by ? " +maigret" : ""}
                      </div>
                    )}

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
                      title="Ver detalles observados de este hallazgo"
                      className="inline-flex items-center gap-1 font-mono text-[11px] font-medium px-2 py-0.5 rounded cursor-pointer transition-colors bg-sky-500/10 text-sky-400 hover:bg-sky-500/20"
                    >
                      <span>Detalles</span>
                      <ChevronDown
                        className={`w-3 h-3 transition-transform ${
                          expanded.has(item.id) ? "rotate-180" : ""
                        }`}
                        aria-hidden="true"
                      />
                    </button>
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap text-right">
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-400">
                      <Clock className="w-3 h-3" aria-hidden="true" /> Observado
                    </span>
                  </td>
                </tr>
                {expanded.has(item.id) && (
                  <tr key={`${item.id}-evidence`} className="bg-[#0d131f]">
                    <td colSpan={5} className="px-4 py-4">
                      <div className="max-w-2xl">
                        <div className="text-[10px] font-mono text-slate-400 uppercase mb-2">
                          Registro observado
                        </div>
                        <p className="text-[11px] text-slate-300 leading-snug">
                          Encontrado por <span className="font-mono text-sky-300">{item.source_tool}</span>.
                          Consulta el mapa para ver las conexiones documentadas con otras observaciones.
                        </p>
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

      {filtered.length > 0 && (
        <div className="px-4 py-3 border-t border-[#1e293b] flex flex-wrap items-center justify-between gap-3 text-[11px] font-mono">
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
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={currentPage === 0}
                className="px-2.5 py-1 rounded border border-[#2b3a52] bg-[#182334] text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#223148] transition-colors cursor-pointer"
              >
                Anterior
              </button>
              <span className="text-slate-400" aria-live="polite">
                Página {currentPage + 1} de {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={currentPage >= totalPages - 1}
                className="px-2.5 py-1 rounded border border-[#2b3a52] bg-[#182334] text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#223148] transition-colors cursor-pointer"
              >
                Siguiente
              </button>
            </nav>
          )}
        </div>
      )}
    </div>
  );
}
