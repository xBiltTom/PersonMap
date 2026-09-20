"use client";

import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import Link from "next/link";
import type { InvestigationData } from "@/lib/types";
import { deleteInvestigation, listInvestigations } from "@/lib/api";
import { ENGINE_META, resolveEngine } from "@/lib/engines";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  FolderOpen,
  RefreshCw,
  Search,
  Trash2,
  XCircle,
} from "lucide-react";

type StatusFilter = "all" | "completed" | "running";
const PAGE_SIZES = [10, 20, 50, "all"] as const;
type PageSize = (typeof PAGE_SIZES)[number];
const REGISTRY_BATCH_SIZE = 100;

function parsePageSize(value: string): PageSize {
  if (value === "all") return "all";
  const size = Number(value);
  return size === 10 || size === 20 || size === 50 ? size : 20;
}

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

function statusView(status: string) {
  if (status === "completed") return { label: "Completado", icon: CheckCircle2, className: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" };
  if (status === "running" || status === "pending") return { label: "En análisis", icon: RefreshCw, className: "border-sky-500/25 bg-sky-500/10 text-sky-300" };
  return { label: status === "failed" ? "Error" : status, icon: XCircle, className: "border-rose-500/25 bg-rose-500/10 text-rose-300" };
}

function targetLabel(investigation: InvestigationData): string {
  return investigation.target?.full_name || investigation.target?.username || investigation.target?.email || "Objetivo sin identificador";
}

async function listAllInvestigations(): Promise<InvestigationData[]> {
  const records: InvestigationData[] = [];
  let offset = 0;
  while (true) {
    const batch = await listInvestigations(REGISTRY_BATCH_SIZE, offset);
    records.push(...batch);
    if (batch.length < REGISTRY_BATCH_SIZE) return records;
    offset += batch.length;
  }
}

export function InvestigationHistory() {
  const [investigations, setInvestigations] = useState<InvestigationData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [pageSize, setPageSize] = useState<PageSize>(20);
  const [page, setPage] = useState(0);

  const loadData = useCallback(() => {
    setLoading(true);
    void listAllInvestigations()
      .then((data) => {
        setInvestigations(data);
        setError(null);
      })
      .catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "No se pudo cargar el registro de expedientes");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const loadTimer = window.setTimeout(loadData, 0);
    return () => window.clearTimeout(loadTimer);
  }, [loadData]);

  const handleDelete = async (event: MouseEvent<HTMLButtonElement>, id: string, name: string) => {
    event.preventDefault();
    if (!window.confirm(`¿Eliminar el expediente “${name}”? Esta acción no se puede deshacer.`)) return;
    try {
      await deleteInvestigation(id);
      loadData();
    } catch (deleteError: unknown) {
      setError(deleteError instanceof Error ? deleteError.message : "No se pudo eliminar el expediente");
    }
  };

  const filteredInvestigations = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase();
    return investigations.filter((investigation) => {
      const target = targetLabel(investigation).toLocaleLowerCase();
      const matchesSearch = !query || target.includes(query) || investigation.id.toLocaleLowerCase().includes(query) || investigation.target?.university?.toLocaleLowerCase().includes(query);
      if (!matchesSearch) return false;
      if (statusFilter === "completed") return investigation.status === "completed";
      if (statusFilter === "running") return investigation.status === "running" || investigation.status === "pending";
      return true;
    });
  }, [investigations, searchQuery, statusFilter]);

  const counts = useMemo(() => ({
    all: investigations.length,
    completed: investigations.filter((investigation) => investigation.status === "completed").length,
    running: investigations.filter((investigation) => investigation.status === "running" || investigation.status === "pending").length,
  }), [investigations]);

  const filters: Array<{ id: StatusFilter; label: string; count: number }> = [
    { id: "all", label: "Todos", count: counts.all },
    { id: "completed", label: "Completados", count: counts.completed },
    { id: "running", label: "En análisis", count: counts.running },
  ];
  const totalPages = pageSize === "all" ? 1 : Math.max(1, Math.ceil(filteredInvestigations.length / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const visibleInvestigations = useMemo(() => {
    if (pageSize === "all") return filteredInvestigations;
    const start = currentPage * pageSize;
    return filteredInvestigations.slice(start, start + pageSize);
  }, [currentPage, filteredInvestigations, pageSize]);
  const firstVisible = filteredInvestigations.length ? currentPage * (pageSize === "all" ? filteredInvestigations.length : pageSize) + 1 : 0;
  const lastVisible = firstVisible ? firstVisible + visibleInvestigations.length - 1 : 0;

  return (
    <section className="panel-card overflow-hidden border border-[#1b2d43] bg-[#0b121d]" aria-labelledby="dossiers-title">
      <header className="flex flex-col gap-3 border-b border-[#1b2d43] bg-[#0a101a] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[#24425e] bg-[#102034] text-sky-300"><FolderOpen className="h-4 w-4" /></div>
          <div>
            <h1 id="dossiers-title" className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-slate-200">Expedientes</h1>
            <p className="mt-0.5 text-[10px] font-mono text-slate-500">Registro de auditorías ejecutadas</p>
          </div>
        </div>
        <button type="button" onClick={loadData} title="Actualizar expedientes" className="inline-flex w-fit items-center gap-1.5 rounded border border-[#29435e] bg-[#101d2e] px-2.5 py-1.5 font-mono text-[11px] text-slate-300 transition-colors hover:border-sky-400/40 hover:text-sky-100">
          <RefreshCw className={`h-3.5 w-3.5 text-sky-400 ${loading ? "animate-spin" : ""}`} /> Actualizar
        </button>
      </header>

      <div className="flex flex-col gap-2.5 border-b border-[#1b2d43] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <label className="flex max-w-sm flex-1 items-center gap-2 rounded-md border border-[#1c3048] bg-[#080e17] px-2.5 py-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span className="sr-only">Buscar expedientes</span>
          <input value={searchQuery} onChange={(event) => { setSearchQuery(event.target.value); setPage(0); }} placeholder="Nombre, institución o código…" className="w-full bg-transparent font-mono text-xs text-slate-200 outline-none placeholder:text-slate-600" />
        </label>
        <div className="flex items-center gap-1 overflow-x-auto font-mono text-[10px]">
          {filters.map((filter) => <button key={filter.id} type="button" onClick={() => { setStatusFilter(filter.id); setPage(0); }} aria-pressed={statusFilter === filter.id} className={`whitespace-nowrap rounded border px-2 py-1 transition-colors ${statusFilter === filter.id ? "border-sky-500/35 bg-sky-500/15 text-sky-200" : "border-transparent text-slate-500 hover:bg-[#101c2b] hover:text-slate-300"}`}>{filter.label} <span className="text-slate-500">{filter.count}</span></button>)}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-[820px] w-full text-left">
          <thead className="border-b border-[#1b2d43] bg-[#0a101a] font-mono text-[10px] uppercase tracking-[0.1em] text-slate-500">
            <tr><th className="px-4 py-3 sm:px-5">Expediente</th><th className="px-4 py-3">Estado</th><th className="px-4 py-3">Motor</th><th className="px-4 py-3 text-right">Hallazgos</th><th className="px-4 py-3">Creado</th><th className="px-4 py-3 text-right">Acciones</th></tr>
          </thead>
          <tbody className="divide-y divide-[#17283b]">
            {loading && investigations.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center font-mono text-xs text-slate-500"><RefreshCw className="mx-auto mb-2 h-4 w-4 animate-spin text-sky-400" />Recuperando expedientes…</td></tr>}
            {!loading && error && <tr><td colSpan={6} className="px-5 py-10 text-center"><AlertTriangle className="mx-auto mb-2 h-5 w-5 text-rose-400" /><p className="font-mono text-xs text-slate-300">No se pudo consultar el registro</p><p className="mt-1 font-mono text-[11px] text-slate-500">{error}</p><button type="button" onClick={loadData} className="mt-3 rounded border border-[#31435b] px-2.5 py-1 font-mono text-[11px] text-slate-300 hover:text-sky-200">Reintentar</button></td></tr>}
            {!loading && !error && investigations.length === 0 && <tr><td colSpan={6} className="px-5 py-12 text-center"><FolderOpen className="mx-auto mb-3 h-7 w-7 text-slate-600" /><p className="font-mono text-xs text-slate-300">Aún no hay expedientes registrados.</p><Link href="/auditorias/nueva" className="mt-3 inline-flex font-mono text-[11px] text-sky-300 hover:text-sky-100">Crear una auditoría</Link></td></tr>}
            {!loading && !error && investigations.length > 0 && filteredInvestigations.length === 0 && <tr><td colSpan={6} className="px-5 py-10 text-center font-mono text-xs text-slate-500">No hay expedientes que coincidan con los filtros.</td></tr>}
            {!error && visibleInvestigations.map((investigation) => {
              const target = targetLabel(investigation);
              const code = `PM-${investigation.id.slice(0, 6).toUpperCase()}`;
              const engine = ENGINE_META[resolveEngine(investigation.strategy, investigation.metrics)];
              const status = statusView(investigation.status);
              const StatusIcon = status.icon;
              return <tr key={investigation.id} className="group transition-colors hover:bg-[#0f1a28]"><td className="max-w-[300px] px-4 py-3 sm:px-5"><Link href={`/investigation/${investigation.id}`} className="block min-w-0"><span className="block truncate font-medium text-slate-200 group-hover:text-sky-200">{target}</span><span className="mt-0.5 block font-mono text-[10px] text-slate-500">{code}{investigation.target?.university ? ` · ${investigation.target.university}` : ""}</span></Link></td><td className="px-4 py-3"><span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px] ${status.className}`}><StatusIcon className={`h-2.5 w-2.5 ${investigation.status === "running" || investigation.status === "pending" ? "animate-spin" : ""}`} />{status.label}</span></td><td className="px-4 py-3"><span className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[9px] ${engine.badge}`}>{engine.label}</span></td><td className="px-4 py-3 text-right font-mono text-xs text-sky-200">{investigation.entities?.length ?? 0}</td><td className="whitespace-nowrap px-4 py-3 font-mono text-[10px] text-slate-500"><span className="inline-flex items-center gap-1"><CalendarDays className="h-3 w-3 text-slate-600" />{formatDate(investigation.created_at)}</span></td><td className="px-4 py-3 text-right"><div className="inline-flex items-center gap-1"><Link href={`/investigation/${investigation.id}`} title="Abrir expediente" className="rounded p-1.5 text-slate-400 hover:bg-sky-500/10 hover:text-sky-200"><ArrowUpRight className="h-3.5 w-3.5" /></Link><button type="button" onClick={(event) => void handleDelete(event, investigation.id, target)} title="Eliminar expediente" className="rounded p-1.5 text-slate-500 hover:bg-rose-500/10 hover:text-rose-300"><Trash2 className="h-3.5 w-3.5" /></button></div></td></tr>;
            })}
          </tbody>
        </table>
      </div>
      {!error && filteredInvestigations.length > 0 && (
        <footer className="flex flex-col gap-3 border-t border-[#1b2d43] bg-[#0a101a] px-4 py-3 font-mono text-[11px] sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <span className="text-slate-500">Mostrando <span className="text-slate-300">{firstVisible}-{lastVisible}</span> de <span className="text-slate-300">{filteredInvestigations.length}</span>{filteredInvestigations.length !== investigations.length && <span> ({investigations.length} en total)</span>}</span>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-slate-500">Mostrar
              <select value={pageSize} onChange={(event) => { setPageSize(parsePageSize(event.target.value)); setPage(0); }} className="rounded border border-[#29435e] bg-[#101d2e] px-1.5 py-1 font-mono text-[11px] text-slate-200 outline-none focus:border-sky-400">
                {PAGE_SIZES.map((size) => <option key={size} value={size}>{size === "all" ? "Todos" : size}</option>)}
              </select>
            </label>
            {totalPages > 1 && <nav className="flex items-center gap-2" aria-label="Paginación de expedientes"><button type="button" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={currentPage === 0} className="rounded border border-[#29435e] px-2 py-1 text-slate-300 transition-colors hover:text-sky-100 disabled:cursor-not-allowed disabled:opacity-40">Anterior</button><span className="text-slate-500">Página {currentPage + 1} de {totalPages}</span><button type="button" onClick={() => setPage((current) => Math.min(totalPages - 1, current + 1))} disabled={currentPage >= totalPages - 1} className="rounded border border-[#29435e] px-2 py-1 text-slate-300 transition-colors hover:text-sky-100 disabled:cursor-not-allowed disabled:opacity-40">Siguiente</button></nav>}
          </div>
        </footer>
      )}
    </section>
  );
}
