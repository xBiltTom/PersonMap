"use client";

import React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useWorkstation } from "@/context/WorkstationContext";
import {
  Home,
  PlusCircle,
  FolderOpen,
  Network,
  Table,
  Clock,
  Terminal,
  FileText,
  ShieldCheck,
  BarChart3,
  ExternalLink,
  ChevronDown,
} from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const {
    activeInvestigation,
    activeTab,
    setActiveTab,
    isSidebarOpen,
    setIsSidebarOpen,
  } = useWorkstation();

  // Check if we are inside an investigation view
  const isInsideInvestigation = pathname.startsWith("/investigation/");

  const handleSubTabClick = (tabId: string) => {
    setActiveTab(tabId);
    if (activeInvestigation && pathname !== `/investigation/${activeInvestigation.id}`) {
      router.push(`/investigation/${activeInvestigation.id}`);
    }
    setIsSidebarOpen(false);
  };

  return (
    <aside
      className={`fixed md:sticky top-14 z-30 h-[calc(100vh-3.5rem)] w-60 shrink-0 border-r border-[#162234] bg-[#090e17] flex flex-col justify-between select-none transition-transform duration-200 ease-in-out ${
        isSidebarOpen
          ? "translate-x-0 shadow-2xl"
          : "-translate-x-full md:translate-x-0"
      }`}
    >
      {/* Top and middle navigation items */}
      <div className="p-3 space-y-6 overflow-y-auto">
        {/* Global Primary Navigation */}
        <nav className="space-y-1">
          <Link
            href="/"
            onClick={() => setIsSidebarOpen(false)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono transition-colors ${
              pathname === "/"
                ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
            }`}
          >
            <Home className="w-4 h-4 text-sky-400 shrink-0" />
            <span>Inicio</span>
          </Link>

          <Link
            href="/?action=new"
            onClick={() => setIsSidebarOpen(false)}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent transition-colors"
          >
            <PlusCircle className="w-4 h-4 text-sky-400 shrink-0" />
            <span>Nueva auditoría</span>
          </Link>

          <Link
            href="/#historial"
            onClick={() => setIsSidebarOpen(false)}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent transition-colors"
          >
            <FolderOpen className="w-4 h-4 text-sky-400 shrink-0" />
            <span>Expedientes</span>
          </Link>
        </nav>

        {/* Contextual: EXPEDIENTE ACTUAL */}
        {(isInsideInvestigation || activeInvestigation) && (
          <div className="pt-2 border-t border-[#162234] space-y-2">
            <div className="px-3 flex items-center justify-between">
              <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500">
                Expediente actual
              </span>
            </div>

            {/* Target Card Header */}
            <div className="p-2.5 rounded-lg bg-[#0d1420] border border-[#1a2636]">
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono text-xs font-semibold text-slate-200 truncate">
                  {activeInvestigation?.targetName || "Expediente activo"}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-500 shrink-0" />
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-[10px] font-mono text-slate-400">
                  {activeInvestigation?.code || "PM-CASE"}
                </span>
                <span
                  className={`text-[9px] font-mono px-1.5 py-0.2 rounded font-medium border ${
                    activeInvestigation?.status === "completed"
                      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
                      : activeInvestigation?.status === "running"
                      ? "bg-sky-500/10 text-sky-300 border-sky-500/30 animate-pulse"
                      : "bg-amber-500/10 text-amber-300 border-amber-500/30"
                  }`}
                >
                  {activeInvestigation?.status === "completed"
                    ? "Completado"
                    : activeInvestigation?.status === "running"
                    ? "En análisis"
                    : activeInvestigation?.status || "Activo"}
                </span>
              </div>
            </div>

            {/* Subnav links inside the investigation */}
            <div className="space-y-0.5 pt-1">
              <button
                type="button"
                onClick={() => handleSubTabClick("graph")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab === "graph"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Network className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Mapa digital</span>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleSubTabClick("findings")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab === "findings"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Table className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Hallazgos</span>
                </div>
                {typeof activeInvestigation?.findingsCount === "number" && (
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#162234] text-slate-300 border border-[#22344d]">
                    {activeInvestigation.findingsCount}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => handleSubTabClick("timeline")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab === "timeline"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Clock className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Línea de tiempo</span>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleSubTabClick("console")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab === "console"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Terminal className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Consola</span>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleSubTabClick("report")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab === "report"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <FileText className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Informe</span>
                </div>
              </button>
            </div>
          </div>
        )}

        {/* Auxiliary Navigation */}
        <div className="pt-2 border-t border-[#162234] space-y-1">
          <Link
            href="/seguridad"
            onClick={() => setIsSidebarOpen(false)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono transition-colors ${
              pathname === "/seguridad"
                ? "bg-[#142032] text-amber-300 font-semibold border border-[#213550]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
            }`}
          >
            <ShieldCheck className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Autodefensa</span>
          </Link>

          <Link
            href="/evaluation"
            onClick={() => setIsSidebarOpen(false)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono transition-colors ${
              pathname === "/evaluation"
                ? "bg-[#142032] text-purple-300 font-semibold border border-[#213550]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
            }`}
          >
            <BarChart3 className="w-4 h-4 text-purple-400 shrink-0" />
            <span>Evaluación</span>
          </Link>

          <a
            href="https://github.com/xBiltTom/PersonMap"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between px-3 py-2 rounded-lg text-xs font-mono text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent transition-colors"
          >
            <div className="flex items-center gap-2.5">
              <FileText className="w-4 h-4 text-slate-500 shrink-0" />
              <span>Documentación</span>
            </div>
            <ExternalLink className="w-3 h-3 text-slate-600" />
          </a>
        </div>
      </div>

      {/* Footer Disclaimer */}
      <div className="p-3.5 border-t border-[#162234] bg-[#070b13] text-[10px] font-mono text-slate-500 space-y-1.5">
        <p className="font-semibold text-slate-400">PersonMap v0.2.0</p>
        <p className="text-[9px] leading-tight text-slate-600">
          Proyecto académico — Uso ético y de auditoría personal.
        </p>
        <div className="pt-1 flex items-center gap-2 text-[9px] text-slate-600">
          <span>Términos</span>
          <span>·</span>
          <span>Privacidad</span>
        </div>
      </div>
    </aside>
  );
}
