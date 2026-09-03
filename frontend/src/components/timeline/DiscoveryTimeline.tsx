"use client";

import { EntityData } from "@/lib/types";
import { Clock, ExternalLink, ShieldCheck } from "lucide-react";

export function DiscoveryTimeline({ entities }: { entities: EntityData[] }) {
  const sorted = [...entities].sort(
    (a, b) => new Date(a.discovered_at).getTime() - new Date(b.discovered_at).getTime()
  );

  if (sorted.length === 0) {
    return (
      <div className="panel-card p-8 text-center text-slate-500 font-mono text-xs">
        No hay registros cronológicos todavía.
      </div>
    );
  }

  return (
    <div className="panel-card p-6">
      <div className="flex items-center gap-2 pb-4 border-b border-[#1e293b] mb-6">
        <Clock className="w-4 h-4 text-sky-400" />
        <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-slate-200">
          Secuencia Cronológica de Extracción y Pivoteo ({sorted.length})
        </h3>
      </div>

      <div className="relative pl-6 border-l border-[#1e293b] space-y-6">
        {sorted.map((item, i) => {
          const time = new Date(item.discovered_at).toLocaleTimeString("es-ES", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          });

          return (
            <div key={item.id} className="relative group">
              {/* Dot */}
              <div className="absolute -left-[31px] top-1 w-3 h-3 rounded-full bg-[#162030] border-2 border-sky-400 group-hover:bg-sky-400 transition-colors" />

              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-[10px] font-mono text-slate-500">[{time}]</span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 uppercase font-semibold">
                  {item.source_tool}
                </span>
                <span className="text-xs font-bold text-slate-200">
                  {item.platform || item.entity_type}
                </span>
                <span className="text-[10px] font-mono text-slate-400 ml-auto">
                  Certeza: {Math.round(item.confidence * 100)}%
                </span>
              </div>

              <div className="text-xs text-slate-300 font-medium">
                {item.display_name || item.value}
              </div>

              {item.value.startsWith("http") && (
                <a
                  href={item.value}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-sky-400 hover:underline flex items-center gap-1 mt-0.5"
                >
                  <span className="truncate max-w-md">{item.value}</span>
                  <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                </a>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
