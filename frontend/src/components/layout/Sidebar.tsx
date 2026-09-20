"use client";

import React, { useState, useRef, useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useWorkstation } from "@/context/WorkstationContext";
import { listInvestigations } from "@/lib/api";
import type { InvestigationData } from "@/lib/types";
import {
  Home,
  PlusCircle,
  FolderOpen,
  Network,
  FileText,
  ShieldCheck,
  BarChart3,
  ExternalLink,
  ChevronDown,
  Search,
  ChevronRight,
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

  // Case Switcher state & logic
  const [isSwitcherOpen, setIsSwitcherOpen] = useState(false);
  const [switcherSearch, setSwitcherSearch] = useState("");
  const [investigationsList, setInvestigationsList] = useState<InvestigationData[]>([]);
  const [loadingSwitcher, setLoadingSwitcher] = useState(false);
  const switcherRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const closeSwitcher = () => {
    setIsSwitcherOpen(false);
    setSwitcherSearch("");
  };

  const toggleSwitcher = () => {
    setIsSwitcherOpen((prev) => {
      const next = !prev;
      if (!next) {
        setSwitcherSearch("");
      } else if (investigationsList.length === 0 && !loadingSwitcher) {
        setLoadingSwitcher(true);
        listInvestigations(25, 0)
          .then((data) => setInvestigationsList(data))
          .catch(() => setInvestigationsList([]))
          .finally(() => setLoadingSwitcher(false));
      }
      return next;
    });
  };

  useEffect(() => {
    if (isSwitcherOpen) {
      const timer = setTimeout(() => searchInputRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    }
  }, [isSwitcherOpen]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (switcherRef.current && !switcherRef.current.contains(e.target as Node)) {
        closeSwitcher();
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isSwitcherOpen) {
        closeSwitcher();
      }
    };
    if (isSwitcherOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isSwitcherOpen]);

  const filteredInvestigations = useMemo(() => {
    const q = switcherSearch.trim().toLowerCase();
    if (!q) return investigationsList;
    return investigationsList.filter((inv) => {
      const code = `PM-${inv.id.slice(0, 4).toUpperCase()}`.toLowerCase();
      const name = (inv.target?.full_name || "").toLowerCase();
      const username = (inv.target?.username || "").toLowerCase();
      const email = (inv.target?.email || "").toLowerCase();
      const dni = (inv.target?.dni || "").toLowerCase();
      return (
        code.includes(q) ||
        name.includes(q) ||
        username.includes(q) ||
        email.includes(q) ||
        dni.includes(q)
      );
    });
  }, [investigationsList, switcherSearch]);

  const handleSelectInvestigation = (inv: InvestigationData) => {
    closeSwitcher();
    setIsSidebarOpen(false);
    router.push(`/investigation/${inv.id}`);
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
            href="/auditorias/nueva"
            onClick={() => setIsSidebarOpen(false)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono transition-colors ${
              pathname === "/auditorias/nueva"
                ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
            }`}
          >
            <PlusCircle className="w-4 h-4 text-sky-400 shrink-0" />
            <span>Nueva auditoría</span>
          </Link>

          <Link
            href="/expedientes"
            onClick={() => setIsSidebarOpen(false)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-mono transition-colors ${
              pathname === "/expedientes"
                ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
            }`}
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

            {/* Target Card Header with Dropdown Switcher */}
            <div ref={switcherRef} className="space-y-1.5">
              <button
                type="button"
                onClick={toggleSwitcher}
                className={`w-full p-2.5 rounded-lg border text-left transition-all cursor-pointer select-none ${
                  isSwitcherOpen
                    ? "bg-[#0e1726] border-sky-500/40 shadow-lg shadow-sky-950/20"
                    : "bg-[#0d1420] border-[#1a2636] hover:border-[#25374d] hover:bg-[#101927]"
                }`}
                aria-expanded={isSwitcherOpen}
                aria-haspopup="listbox"
                title="Cambiar de expediente"
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="font-mono text-xs font-semibold text-slate-200 truncate">
                    {activeInvestigation?.targetName || "Expediente activo"}
                  </span>
                  <ChevronDown
                    className={`w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform duration-200 ${
                      isSwitcherOpen ? "rotate-180 text-sky-400" : ""
                    }`}
                  />
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
              </button>

              {/* Accordion Dropdown Content */}
              {isSwitcherOpen && (
                <div className="rounded-lg border border-[#1e2f46] bg-[#070e18] p-2 shadow-2xl animate-fade-in space-y-2">
                  {/* Minibuscador */}
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
                    <input
                      ref={searchInputRef}
                      type="text"
                      value={switcherSearch}
                      onChange={(e) => setSwitcherSearch(e.target.value)}
                      placeholder="Filtrar expedientes..."
                      className="w-full pl-7 pr-2.5 py-1 rounded-md border border-[#1b2b3e] bg-[#0c1422] font-mono text-[11px] text-slate-200 placeholder-slate-500 focus:border-sky-400 focus:outline-none"
                    />
                  </div>

                  {/* Lista Scrolleable */}
                  <div className="max-h-48 overflow-y-auto space-y-0.5 custom-scrollbar pr-0.5">
                    {loadingSwitcher ? (
                      <div className="py-4 text-center">
                        <div className="w-4 h-4 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mx-auto mb-1.5" />
                        <span className="text-[10px] font-mono text-slate-500">Cargando expedientes...</span>
                      </div>
                    ) : filteredInvestigations.length === 0 ? (
                      <div className="py-3 text-center text-[10px] font-mono text-slate-500">
                        {switcherSearch ? "Sin coincidencias" : "No hay otros expedientes"}
                      </div>
                    ) : (
                      filteredInvestigations.map((inv) => {
                        const isCurrent = activeInvestigation?.id === inv.id;
                        const code = `PM-${inv.id.slice(0, 4).toUpperCase()}`;
                        const targetLabel =
                          inv.target?.full_name ||
                          inv.target?.username ||
                          inv.target?.email ||
                          inv.target?.dni ||
                          "Sin objetivo";

                        return (
                          <button
                            key={inv.id}
                            type="button"
                            onClick={() => handleSelectInvestigation(inv)}
                            className={`w-full flex items-center justify-between p-1.5 rounded-md text-left transition-colors text-xs font-mono cursor-pointer ${
                              isCurrent
                                ? "bg-sky-500/15 border border-sky-500/30 text-sky-200"
                                : "hover:bg-[#101a28] text-slate-300 border border-transparent"
                            }`}
                          >
                            <div className="min-w-0 pr-1">
                              <span className="block truncate text-[11px] font-medium leading-tight text-slate-200">
                                {targetLabel}
                              </span>
                              <span className="text-[9px] text-slate-500">{code}</span>
                            </div>

                            <span
                              className={`shrink-0 w-2 h-2 rounded-full ${
                                inv.status === "completed"
                                  ? "bg-emerald-400"
                                  : inv.status === "running"
                                  ? "bg-sky-400 animate-pulse"
                                  : inv.status === "failed"
                                  ? "bg-rose-400"
                                  : "bg-amber-400"
                              }`}
                              title={inv.status}
                            />
                          </button>
                        );
                      })
                    )}
                  </div>

                  {/* Footer link: Ver todos */}
                  <div className="pt-1.5 border-t border-[#162234] flex items-center justify-between px-1">
                    <Link
                      href="/expedientes"
                      onClick={() => {
                        closeSwitcher();
                        setIsSidebarOpen(false);
                      }}
                      className="text-[10px] font-mono text-slate-400 hover:text-sky-300 transition-colors inline-flex items-center gap-1"
                    >
                      <span>Ver todos</span>
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                    <span className="text-[9px] font-mono text-slate-600">
                      {investigationsList.length} casos
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Subnav links inside the investigation: Workspace and Informe */}
            <div className="space-y-0.5 pt-1">
              <button
                type="button"
                onClick={() => handleSubTabClick("findings")}
                className={`w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-mono transition-colors text-left ${
                  isInsideInvestigation && activeTab !== "report"
                    ? "bg-[#142032] text-sky-300 font-semibold border border-[#213550]"
                    : "text-slate-400 hover:text-slate-200 hover:bg-[#0e1624] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Network className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                  <span className="truncate">Workspace</span>
                </div>
                {typeof activeInvestigation?.findingsCount === "number" && (
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#162234] text-slate-300 border border-[#22344d]">
                    {activeInvestigation.findingsCount}
                  </span>
                )}
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
        <p className="font-semibold text-slate-400">PersonMap v0.1.0</p>
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
