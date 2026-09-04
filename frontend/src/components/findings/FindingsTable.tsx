"use client";

import { useState, useMemo } from "react";
import { EntityData } from "@/lib/types";
import { Search, ExternalLink, CheckCircle, Clock } from "lucide-react";

export function FindingsTable({ entities }: { entities: EntityData[] }) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");

  const filtered = useMemo(() => {
    return entities.filter((e) => {
      const matchSearch =
        (e.display_name || "").toLowerCase().includes(search.toLowerCase()) ||
        (e.value || "").toLowerCase().includes(search.toLowerCase()) ||
        (e.platform || "").toLowerCase().includes(search.toLowerCase());

      const matchType =
        filterType === "all" ||
        e.entity_type === filterType ||
        (filterType === "social" && e.entity_type === "social_account") ||
        (filterType === "academic" && e.entity_type === "academic");

      return matchSearch && matchType;
    });
  }, [entities, search, filterType]);

  const categories = [
    { id: "all", label: "Todos" },
    { id: "social_account", label: "Redes / Cuentas" },
    { id: "email", label: "Correos" },
    { id: "breach", label: "Filtraciones / Brechas" },
    { id: "phone", label: "Telefonía" },
    { id: "academic", label: "Académico" },
    { id: "search_mention", label: "Dorks / Menciones" },
    { id: "document", label: "Documentos (DNI)" },
  ];

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
              onClick={() => setFilterType(cat.id)}
              className={`text-[11px] font-mono px-2.5 py-1 rounded transition-colors whitespace-nowrap ${
                filterType === cat.id
                  ? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
                  : "bg-[#131b26] text-slate-400 hover:text-slate-200 border border-transparent"
              }`}
            >
              {cat.label}
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
              filtered.map((item) => (
                <tr key={item.id} className="hover:bg-[#151e2c] transition-colors">
                  <td className="py-3 px-4 whitespace-nowrap">
                    <div className="font-semibold text-slate-200">
                      {item.platform || item.entity_type}
                    </div>
                    <div className="text-[10px] font-mono text-slate-500 uppercase">
                      {item.entity_type}
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
                    {item.source_tool}
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap text-center">
                    <span
                      className={`font-mono text-[11px] font-bold px-2 py-0.5 rounded ${
                        item.confidence >= 0.70
                          ? "bg-emerald-500/10 text-emerald-400"
                          : item.confidence >= 0.40
                          ? "bg-sky-500/10 text-sky-400"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {Math.round(item.confidence * 100)}%
                    </span>
                  </td>

                  <td className="py-3 px-4 whitespace-nowrap text-right">
                    {item.verified ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono text-emerald-400">
                        <CheckCircle className="w-3 h-3" /> Verificado
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-500">
                        <Clock className="w-3 h-3" /> Pendiente
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
