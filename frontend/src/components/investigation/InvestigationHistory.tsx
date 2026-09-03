"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { InvestigationData } from "@/lib/types";
import { listInvestigations, deleteInvestigation } from "@/lib/api";
import {
  FolderOpen,
  Calendar,
  AlertTriangle,
  ChevronRight,
  Trash2,
  Cpu,
  Workflow,
  CheckCircle2,
  Clock,
  XCircle,
} from "lucide-react";

export function InvestigationHistory() {
  const [investigations, setInvestigations] = useState<InvestigationData[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = () => {
    setLoading(true);
    listInvestigations()
      .then(setInvestigations)
      .catch(() => setInvestigations([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (confirm("¿Estás seguro de eliminar esta investigación?")) {
      await deleteInvestigation(id);
      loadData();
    }
  };

  if (loading) {
    return (
      <div className="panel-card p-6 flex items-center justify-center text-xs font-mono text-slate-500 py-12">
        <span className="w-4 h-4 border-2 border-sky-500/30 border-t-sky-400 rounded-full animate-spin mr-2"></span>
        Cargando expediente histórico...
      </div>
    );
  }

  if (investigations.length === 0) {
    return (
      <div className="panel-card p-8 text-center">
        <FolderOpen className="w-10 h-10 text-slate-600 mx-auto mb-2 opacity-50" />
        <h3 className="text-sm font-semibold text-slate-300">No hay investigaciones registradas</h3>
        <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
          Inicia tu primera investigación con el formulario superior para construir el primer mapa digital.
        </p>
      </div>
    );
  }

  return (
    <div className="panel-card overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1e293b] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-sky-400" />
          <h3 className="text-xs font-mono font-semibold tracking-wider text-slate-200 uppercase">
            Expedientes de Huella Digital ({investigations.length})
          </h3>
        </div>
        <span className="text-[11px] font-mono text-slate-500">Historial Local</span>
      </div>

      <div className="divide-y divide-[#182234]">
        {investigations.map((inv) => {
          const targetName =
            inv.target?.full_name ||
            inv.target?.username ||
            inv.target?.email ||
            "Objetivo Anónimo";

          const isCompleted = inv.status === "completed";
          const isRunning = inv.status === "running";
          const isFailed = inv.status === "failed";

          return (
            <Link
              key={inv.id}
              href={`/investigation/${inv.id}`}
              className="px-5 py-4 flex items-center justify-between hover:bg-[#151e2c] transition-colors group block"
            >
              <div className="flex items-center gap-4 min-w-0">
                {/* Status Indicator */}
                <div className="shrink-0">
                  {isCompleted ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  ) : isRunning ? (
                    <Clock className="w-5 h-5 text-sky-400 animate-spin" />
                  ) : isFailed ? (
                    <XCircle className="w-5 h-5 text-rose-400" />
                  ) : (
                    <Clock className="w-5 h-5 text-amber-400" />
                  )}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-200 group-hover:text-sky-300 transition-colors truncate">
                      {targetName}
                    </span>
                    {inv.target?.university && (
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#1b2537] text-slate-400 border border-[#2b3a52] shrink-0">
                        {inv.target.university}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3 mt-1 text-[11px] font-mono text-slate-500">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3 h-3" />
                      {new Date(inv.created_at).toLocaleDateString("es-ES", {
                        day: "2-digit",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>

                    <span className="flex items-center gap-1">
                      {inv.strategy === "agentic" ? (
                        <Cpu className="w-3 h-3 text-purple-400" />
                      ) : (
                        <Workflow className="w-3 h-3 text-sky-400" />
                      )}
                      <span className="uppercase">{inv.strategy}</span>
                    </span>

                    {inv.metrics?.entities_discovered !== undefined && (
                      <span>{inv.metrics.entities_discovered} entidades</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 shrink-0 ml-4">
                {isCompleted && (
                  <div className="text-right">
                    <div className="flex items-center gap-1.5 justify-end">
                      <span
                        className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                          inv.risk_score >= 75
                            ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            : inv.risk_score >= 50
                            ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                            : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        }`}
                      >
                        {inv.risk_score}/100
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase">
                      {inv.metrics?.risk_level || "Riesgo"}
                    </span>
                  </div>
                )}

                <button
                  onClick={(e) => handleDelete(e, inv.id)}
                  title="Eliminar investigación"
                  className="p-1.5 rounded hover:bg-rose-500/10 text-slate-500 hover:text-rose-400 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>

                <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-300 transition-colors" />
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
