"use client";

import React, { useState, useMemo, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useWorkstation } from "@/context/WorkstationContext";
import {
  Search,
  Home,
  PlusCircle,
  FolderOpen,
  ShieldCheck,
  BarChart3,
  Network,
  Table,
  Clock,
  Terminal,
  FileText,
  ExternalLink,
  X,
  Command,
} from "lucide-react";

interface PaletteAction {
  id: string;
  category: "Navegación" | "Expediente Activo" | "Recursos";
  title: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  perform: () => void;
}

function CommandPaletteModal() {
  const router = useRouter();
  const {
    setIsCommandPaletteOpen,
    activeInvestigation,
    setActiveTab,
  } = useWorkstation();

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const actions: PaletteAction[] = useMemo(() => {
    const list: PaletteAction[] = [
      {
        id: "nav-home",
        category: "Navegación",
        title: "Inicio / Consola de Despacho",
        subtitle: "Lanzador de investigaciones y resumen general",
        icon: Home,
        perform: () => {
          router.push("/");
          setIsCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-new",
        category: "Navegación",
        title: "Nueva auditoría",
        subtitle: "Configurar un nuevo objetivo OSINT",
        icon: PlusCircle,
        perform: () => {
          router.push("/?action=new");
          setIsCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-cases",
        category: "Navegación",
        title: "Historial de expedientes",
        subtitle: "Consultar auditorías previas archivadas",
        icon: FolderOpen,
        perform: () => {
          router.push("/#historial");
          setIsCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-defense",
        category: "Navegación",
        title: "Autodefensa (K-Anonymity HIBP)",
        subtitle: "Comprobar exposición de contraseñas de forma privada",
        icon: ShieldCheck,
        perform: () => {
          router.push("/seguridad");
          setIsCommandPaletteOpen(false);
        },
      },
      {
        id: "nav-eval",
        category: "Navegación",
        title: "Métricas y Evaluación Científica",
        subtitle: "Comparativa experimental de motores para el paper",
        icon: BarChart3,
        perform: () => {
          router.push("/evaluation");
          setIsCommandPaletteOpen(false);
        },
      },
    ];

    if (activeInvestigation) {
      list.push(
        {
          id: "exp-graph",
          category: "Expediente Activo",
          title: `Mapa digital: ${activeInvestigation.targetName}`,
          subtitle: `Código ${activeInvestigation.code} · Explorar constelación`,
          icon: Network,
          perform: () => {
            setActiveTab("graph");
            router.push(`/investigation/${activeInvestigation.id}`);
            setIsCommandPaletteOpen(false);
          },
        },
        {
          id: "exp-findings",
          category: "Expediente Activo",
          title: `Hallazgos documentados (${activeInvestigation.findingsCount ?? 0})`,
          subtitle: "Tabla densa con evidencias y procedencia",
          icon: Table,
          perform: () => {
            setActiveTab("findings");
            router.push(`/investigation/${activeInvestigation.id}`);
            setIsCommandPaletteOpen(false);
          },
        },
        {
          id: "exp-timeline",
          category: "Expediente Activo",
          title: "Línea de tiempo de descubrimientos",
          subtitle: "Cronología de eventos y hallazgos",
          icon: Clock,
          perform: () => {
            setActiveTab("timeline");
            router.push(`/investigation/${activeInvestigation.id}`);
            setIsCommandPaletteOpen(false);
          },
        },
        {
          id: "exp-console",
          category: "Expediente Activo",
          title: "Consola de eventos en vivo",
          subtitle: "Telemetría del stream SSE en tiempo real",
          icon: Terminal,
          perform: () => {
            setActiveTab("console");
            router.push(`/investigation/${activeInvestigation.id}`);
            setIsCommandPaletteOpen(false);
          },
        },
        {
          id: "exp-report",
          category: "Expediente Activo",
          title: "Informe forense de concientización",
          subtitle: "Síntesis de exposición digital e impresión PDF",
          icon: FileText,
          perform: () => {
            setActiveTab("report");
            router.push(`/investigation/${activeInvestigation.id}`);
            setIsCommandPaletteOpen(false);
          },
        }
      );
    }

    list.push({
      id: "res-docs",
      category: "Recursos",
      title: "Documentación metodológica",
      subtitle: "Arquitectura OSINT y reglas de correlación",
      icon: ExternalLink,
      perform: () => {
        window.open(
          "https://github.com/xBiltTom/PersonMap",
          "_blank",
          "noopener,noreferrer"
        );
        setIsCommandPaletteOpen(false);
      },
    });

    return list;
  }, [activeInvestigation, router, setActiveTab, setIsCommandPaletteOpen]);

  const filtered = useMemo(() => {
    if (!query.trim()) return actions;
    const q = query.toLowerCase();
    return actions.filter(
      (a) =>
        a.title.toLowerCase().includes(q) ||
        (a.subtitle && a.subtitle.toLowerCase().includes(q)) ||
        a.category.toLowerCase().includes(q)
    );
  }, [actions, query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filtered.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filtered.length) % Math.max(1, filtered.length));
    } else if (e.key === "Enter" && filtered[selectedIndex]) {
      e.preventDefault();
      filtered[selectedIndex].perform();
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Paleta de comandos"
      className="fixed inset-0 z-[100] flex items-start justify-center pt-20 px-4 bg-black/75 backdrop-blur-sm animate-fade-in"
      onClick={() => setIsCommandPaletteOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-[#22344d] bg-[#0c131f] shadow-2xl shadow-black/80"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Input Header */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-[#162234] bg-[#090f18]">
          <Search className="w-4 h-4 text-sky-400 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              activeInvestigation
                ? `Buscar en ${activeInvestigation.targetName} o navegar...`
                : "Buscar comando, vista o sección (⌘K)..."
            }
            className="flex-1 bg-transparent font-mono text-xs text-slate-100 placeholder-slate-500 outline-none"
          />
          <button
            type="button"
            onClick={() => setIsCommandPaletteOpen(false)}
            className="rounded p-1 text-slate-500 hover:text-slate-200"
            aria-label="Cerrar búsqueda"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results list */}
        <div className="max-h-[360px] overflow-y-auto p-2 divide-y divide-transparent">
          {filtered.length === 0 ? (
            <div className="py-8 text-center text-xs font-mono text-slate-500">
              No se encontraron acciones ni elementos para &ldquo;{query}&rdquo;.
            </div>
          ) : (
            filtered.map((action, idx) => {
              const Icon = action.icon;
              const isSelected = idx === selectedIndex;
              return (
                <button
                  key={action.id}
                  type="button"
                  onClick={action.perform}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex w-full items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                    isSelected
                      ? "bg-[#162438] text-slate-100 border border-[#263e5c]"
                      : "text-slate-300 hover:bg-[#111a28] border border-transparent"
                  }`}
                >
                  <div
                    className={`flex h-7 w-7 items-center justify-center rounded border shrink-0 ${
                      isSelected
                        ? "border-sky-400/40 bg-sky-500/10 text-sky-300"
                        : "border-[#1c2c40] bg-[#0e1624] text-slate-400"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-medium truncate">
                        {action.title}
                      </span>
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[#101b2b] text-slate-400 border border-[#1b2b40]">
                        {action.category}
                      </span>
                    </div>
                    {action.subtitle && (
                      <p className="font-mono text-[10px] text-slate-500 truncate mt-0.5">
                        {action.subtitle}
                      </p>
                    )}
                  </div>
                  {isSelected && (
                    <span className="font-mono text-[10px] text-sky-400 shrink-0">
                      ↵ Enter
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Footer shortcuts info */}
        <div className="flex items-center justify-between px-4 py-2 border-t border-[#162234] bg-[#080d15] text-[10px] font-mono text-slate-500">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="px-1 py-0.5 rounded bg-[#121c2c] border border-[#1c2b40] text-slate-400">
                ↑↓
              </kbd>{" "}
              para navegar
            </span>
            <span>
              <kbd className="px-1 py-0.5 rounded bg-[#121c2c] border border-[#1c2b40] text-slate-400">
                ↵
              </kbd>{" "}
              para seleccionar
            </span>
            <span>
              <kbd className="px-1 py-0.5 rounded bg-[#121c2c] border border-[#1c2b40] text-slate-400">
                ESC
              </kbd>{" "}
              para cerrar
            </span>
          </div>
          <div className="flex items-center gap-1 text-slate-400">
            <Command className="w-3 h-3 text-sky-400" />
            <span>PersonMap Workstation</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function CommandPalette() {
  const { isCommandPaletteOpen } = useWorkstation();
  if (!isCommandPaletteOpen) return null;
  return <CommandPaletteModal />;
}
