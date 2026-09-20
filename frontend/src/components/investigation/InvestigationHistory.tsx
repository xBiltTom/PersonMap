"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { InvestigationData } from "@/lib/types";
import { listInvestigations, deleteInvestigation } from "@/lib/api";
import { resolveEngine, ENGINE_META } from "@/lib/engines";
import {
  FolderOpen,
  Calendar,
  AlertTriangle,
  Trash2,
  CheckCircle2,
  Clock,
  XCircle,
  Search,
  RefreshCw,
  ArrowUpRight,
} from "lucide-react";

function formatDate(value?: string): string {
  if (!value) return "Fecha desconocida";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-PE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getInitials(name: string): string {
  if (!name) return "PM";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function InvestigationHistory() {
  const [investigations, setInvestigations] = useState<InvestigationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "running">("all");

  const loadData = () => {
    setLoading(true);
    listInvestigations(50, 0)
      .then((data) => {
        setInvestigations(data);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "No se pudo cargar el historial")
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const initialLoad = window.setTimeout(loadData, 0);
    return () => clearTimeout(initialLoad);
  }, []);

  const handleDelete = async (e: React.MouseEvent, id: string, name: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`¿Estás seguro de eliminar el expediente "${name}"? Esta acción no se puede deshacer.`)) return;

    try {
      await deleteInvestigation(id);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar la investigación");
    }
  };

  const filteredInvestigations = useMemo(() => {
    return investigations.filter((inv) => {
      const name = inv.target?.full_name || inv.target?.username || inv.target?.email || "";
      const matchesSearch =
        !searchQuery.trim() ||
        name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        inv.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (inv.target?.university && inv.target.university.toLowerCase().includes(searchQuery.toLowerCase()));

      if (!matchesSearch) return false;

      if (statusFilter === "completed") return inv.status === "completed";
      if (statusFilter === "running") return inv.status === "running" || inv.status === "pending";
      return true;
    });
  }, [investigations, searchQuery, statusFilter]);

  const completedCount = useMemo(
    () => investigations.filter((i) => i.status === "completed").length,
    [investigations]
  );
  const runningCount = useMemo(
    () => investigations.filter((i) => i.status === "running" || i.status === "pending").length,
    [investigations]
  );

  return (
    <div id="historial" className="panel-card overflow-hidden border border-[#162234] bg-[#0d1420] shadow-xl">
      {/* Header bar */}
      <div className="px-5 py-4 border-b border-[#162234] flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#090f18]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-[#142032] border border-[#213550] flex items-center justify-center text-sky-400">
            <FolderOpen className="w-3.5 h-3.5" />
          </div>
          <div>
            <h3 className="text-xs font-mono font-semibold tracking-wider text-slate-200 uppercase flex items-center gap-2">
              <span>Expedientes Archivados</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#162234] text-slate-400 border border-[#22344d]">
                {investigations.length}
              </span>
            </h3>
            <p className="text-[10px] font-mono text-slate-500">
              Auditorías de huella digital almacenadas localmente
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={loadData}
          title="Refrescar expedientes"
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#101928] hover:bg-[#162438] text-slate-300 text-xs font-mono border border-[#1d2c42] transition-colors cursor-pointer self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 text-sky-400 ${loading ? "animate-spin" : ""}`} />
          <span>Actualizar</span>
        </button>
      </div>

      {/* Filter and Search Toolbar */}
      <div className="p-3 sm:px-5 sm:py-3 border-b border-[#162234] flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5 bg-[#0b111c]">
        {/* Search */}
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[#080d15] border border-[#1a2636] flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filtrar por nombre, universidad o ID..."
            className="w-full bg-transparent font-mono text-xs text-slate-200 placeholder-slate-500 outline-none"
          />
        </div>

        {/* Status filters */}
        <div className="flex items-center gap-1 text-[11px] font-mono shrink-0">
          <button
            type="button"
            onClick={() => setStatusFilter("all")}
            className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "all"
                ? "bg-[#162438] text-sky-300 font-semibold border border-[#263e5c]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#101928]"
            }`}
          >
            Todos ({investigations.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("completed")}
            className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "completed"
                ? "bg-emerald-500/15 text-emerald-300 font-semibold border border-emerald-500/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#101928]"
            }`}
          >
            Completados ({completedCount})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("running")}
            className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
              statusFilter === "running"
                ? "bg-sky-500/15 text-sky-300 font-semibold border border-sky-500/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#101928]"
            }`}
          >
            En análisis ({runningCount})
          </button>
        </div>
      </div>

      {/* Body States */}
      {loading && investigations.length === 0 && (
        <div className="p-12 text-center text-xs font-mono text-slate-400">
          <div className="w-5 h-5 border-2 border-sky-500/30 border-t-sky-400 rounded-full animate-spin mx-auto mb-3" />
          <span>Recuperando expedientes archivados...</span>
        </div>
      )}

      {error && (
        <div className="p-8 text-center border-t border-rose-500/20 bg-rose-500/5">
          <AlertTriangle className="w-8 h-8 text-rose-400 mx-auto mb-2" />
          <h4 className="text-xs font-mono font-semibold text-slate-200">
            Error al consultar el historial local
          </h4>
          <p className="text-[11px] font-mono text-slate-400 mt-1">{error}</p>
          <button
            type="button"
            onClick={loadData}
            className="mt-3 px-3 py-1 rounded bg-[#182334] text-xs font-mono text-slate-200 border border-[#2b3a52] hover:bg-[#223148] transition-colors cursor-pointer"
          >
            Reintentar
          </button>
        </div>
      )}

      {!loading && !error && investigations.length === 0 && (
        <div className="p-12 text-center">
          <FolderOpen className="w-9 h-9 text-slate-600 mx-auto mb-3 opacity-40" />
          <h4 className="text-xs font-mono font-semibold text-slate-300">
            No hay expedientes registrados aún
          </h4>
          <p className="text-[11px] font-mono text-slate-500 mt-1 max-w-sm mx-auto">
            Configura y despacha tu primera investigación en la consola superior para trazar el primer mapa de identidad.
          </p>
        </div>
      )}

      {!loading && !error && investigations.length > 0 && filteredInvestigations.length === 0 && (
        <div className="p-8 text-center text-xs font-mono text-slate-500">
          No hay expedientes que coincidan con &ldquo;{searchQuery}&rdquo;.
        </div>
      )}

      {/* List of Dossiers */}
      {!loading && filteredInvestigations.length > 0 && (
        <div className="divide-y divide-[#162234]">
          {filteredInvestigations.map((inv) => {
            const targetName =
              inv.target?.full_name ||
              inv.target?.username ||
              inv.target?.email ||
              "Objetivo Anónimo";

            const code = `PM-${inv.id.slice(0, 4).toUpperCase()}`;
            const initials = getInitials(targetName);
            const isCompleted = inv.status === "completed";
            const isRunning = inv.status === "running" || inv.status === "pending";
            const isFailed = inv.status === "failed";
            const engineKey = resolveEngine(inv.strategy, inv.metrics);
            const engine = ENGINE_META[engineKey];
            const entitiesCount = inv.entities?.length ?? 0;

            return (
              <div
                key={inv.id}
                className="px-4 sm:px-5 py-3.5 flex items-center justify-between gap-3 hover:bg-[#101928] transition-colors group"
              >
                {/* Left: Avatar + Details */}
                <div className="flex items-center gap-3.5 min-w-0 flex-1">
                  {/* Avatar badge */}
                  <div className="w-9 h-9 rounded-lg bg-[#121d2e] border border-[#20324c] flex items-center justify-center font-mono font-bold text-xs text-sky-300 shrink-0 shadow-sm">
                    {initials}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/investigation/${inv.id}`}
                        className="font-mono text-xs font-semibold text-slate-100 hover:text-sky-300 transition-colors truncate"
                      >
                        {targetName}
                      </Link>

                      <span className="text-[10px] font-mono text-slate-500">
                        {code}
                      </span>

                      {/* Engine badge */}
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${engine.badge}`}
                      >
                        {engine.label}
                      </span>

                      {/* Status indicator */}
                      <span
                        className={`inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.2 rounded font-medium ${
                          isCompleted
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/25"
                            : isRunning
                            ? "bg-sky-500/10 text-sky-400 border border-sky-500/25 animate-pulse"
                            : "bg-rose-500/10 text-rose-400 border border-rose-500/25"
                        }`}
                      >
                        {isCompleted ? (
                          <CheckCircle2 className="w-2.5 h-2.5" />
                        ) : isRunning ? (
                          <Clock className="w-2.5 h-2.5 animate-spin" />
                        ) : (
                          <XCircle className="w-2.5 h-2.5" />
                        )}
                        <span>
                          {isCompleted
                            ? "Completado"
                            : isRunning
                            ? "En análisis"
                            : isFailed
                            ? "Error"
                            : inv.status}
                        </span>
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-[11px] font-mono text-slate-400">
                      {inv.target?.university && (
                        <span className="text-slate-400">
                          🎓 {inv.target.university}
                        </span>
                      )}
                      {inv.target?.email && (
                        <span className="text-slate-500 truncate max-w-[200px]">
                          {inv.target.email}
                        </span>
                      )}
                      <span className="text-slate-500 flex items-center gap-1">
                        <Calendar className="w-3 h-3 text-slate-600" />
                        {formatDate(inv.created_at)}
                      </span>
                      <span className="text-sky-400/80">
                        {entitiesCount} hallazgos
                      </span>
                    </div>
                  </div>
                </div>

                {/* Right: Direct Actions */}
                <div className="flex items-center gap-2 shrink-0">
                  <Link
                    href={`/investigation/${inv.id}`}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[#142032] hover:bg-[#1a2c46] border border-[#213550] text-sky-300 text-xs font-mono transition-colors shadow-sm"
                  >
                    <span>Abrir</span>
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </Link>

                  <button
                    type="button"
                    onClick={(e) => handleDelete(e, inv.id, targetName)}
                    title="Eliminar expediente"
                    className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-colors cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
