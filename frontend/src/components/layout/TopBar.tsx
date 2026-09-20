"use client";

import React, { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { checkHealth } from "@/lib/api";
import { useWorkstation } from "@/context/WorkstationContext";
import {
  Shield,
  Search,
  Command,
  Cpu,
  Menu,
  X,
  User,
  Info,
} from "lucide-react";

const HEALTH_POLL_MS = 15000;

export function TopBar() {
  const { toggleCommandPalette, toggleSidebar, isSidebarOpen, activeInvestigation } = useWorkstation();
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    const ping = async () => {
      try {
        const data = await checkHealth();
        if (!cancelled) {
          setBackendOnline(data.status === "healthy");
          setAiEnabled(data.ai_enabled);
        }
      } catch {
        if (!cancelled) {
          setBackendOnline(false);
          setAiEnabled(false);
        }
      }
    };

    ping();
    const interval = setInterval(ping, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Close profile dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setIsProfileOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header className="h-14 border-b border-[#162234] bg-[#090e17] px-3 sm:px-5 flex items-center justify-between gap-3 sticky top-0 z-40 select-none">
      {/* Left: Brand + Tagline + Mobile toggle */}
      <div className="flex items-center gap-3 shrink-0 min-w-0">
        <button
          type="button"
          onClick={toggleSidebar}
          className="md:hidden p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-[#121c2d]"
          aria-label={isSidebarOpen ? "Cerrar menú lateral" : "Abrir menú lateral"}
        >
          {isSidebarOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
        </button>

        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-[#0e1726] border border-[#1e2f47] flex items-center justify-center text-sky-400 group-hover:border-sky-400/60 transition-colors shadow-sm">
            <Shield className="w-4 h-4" />
          </div>
          <span className="font-mono font-bold text-sm tracking-wide text-slate-100">
            PersonMap
          </span>
        </Link>

        <div className="hidden lg:block h-3.5 w-px bg-[#162234]" />

        <p className="hidden lg:block text-[11px] font-mono text-slate-500 tracking-tight">
          Open Sources. Real Context. Human Judgment.
        </p>
      </div>

      {/* Center: Search trigger (⌘K) */}
      <div className="flex-1 max-w-md mx-auto hidden sm:block">
        <button
          type="button"
          onClick={toggleCommandPalette}
          className="w-full flex items-center justify-between px-3 py-1.5 rounded-lg bg-[#0d1420] border border-[#1a2636] hover:border-[#22344d] text-slate-400 text-xs font-mono transition-colors group cursor-pointer shadow-inner"
        >
          <span className="flex items-center gap-2 truncate">
            <Search className="w-3.5 h-3.5 text-slate-500 group-hover:text-sky-400 transition-colors" />
            <span className="text-slate-400 truncate">
              {activeInvestigation
                ? `Buscar en ${activeInvestigation.targetName}...`
                : "Buscar en este expediente o saltar a..."}
            </span>
          </span>
          <kbd className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-[#131d2b] border border-[#202f45] text-[10px] text-slate-400 font-mono shrink-0">
            <Command className="w-2.5 h-2.5" /> K
          </kbd>
        </button>
      </div>

      {/* Right: Telemetry + Analyst profile */}
      <div className="flex items-center gap-2.5 shrink-0">
        {/* Backend OSINT Engine status */}
        <div
          title={
            backendOnline === true
              ? "Motor OSINT activo en http://localhost:8000"
              : backendOnline === false
              ? "Backend offline. Verifica el puerto 8000"
              : "Verificando conexión con el motor..."
          }
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#0d1522] border border-[#162234] text-[11px] font-mono text-slate-300 cursor-default"
        >
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              backendOnline === true
                ? "bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.6)]"
                : backendOnline === false
                ? "bg-rose-500"
                : "bg-amber-400"
            }`}
          />
          <span className="hidden md:inline text-[11px]">
            {backendOnline === true
              ? "Motor OSINT operativo"
              : backendOnline === false
              ? "Motor Offline"
              : "Conectando..."}
          </span>
        </div>

        {/* LLM availability status */}
        <div
          title={
            aiEnabled === true
              ? "Proveedor LLM configurado en el backend"
              : "Sin LLM configurado (las estrategias de IA degradan a reglas)"
          }
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-mono cursor-default ${
            aiEnabled === true
              ? "bg-[#181028] border-purple-500/30 text-purple-200"
              : "bg-[#0d1522] border-[#162234] text-slate-500"
          }`}
        >
          <Cpu
            className={`w-3 h-3 shrink-0 ${
              aiEnabled === true ? "text-purple-400" : "text-slate-500"
            }`}
          />
          <span className="hidden xl:inline text-[11px]">
            {aiEnabled === true ? "LLM disponible" : "LLM inactivo"}
          </span>
        </div>

        {/* Analyst Profile Menu */}
        {/* <div className="relative" ref={profileRef}>
          <button
            type="button"
            onClick={() => setIsProfileOpen((prev) => !prev)}
            className="flex items-center gap-2 p-1 pl-1.5 pr-2.5 rounded-full bg-[#0e1624] border border-[#1d2c42] hover:border-sky-500/40 text-slate-200 text-xs font-mono transition-colors cursor-pointer"
          >
            <div className="w-5 h-5 rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/40 flex items-center justify-center font-bold text-[10px]">
              B
            </div>
            <span className="font-medium hidden sm:inline">Bilton</span>
            <span className="text-[10px] text-slate-500">▾</span>
          </button>

          {isProfileOpen && (
            <div className="absolute right-0 top-10 w-64 rounded-xl border border-[#22344d] bg-[#0c131f] p-3 shadow-2xl z-50 animate-fade-in text-xs font-mono">
              <div className="flex items-center gap-2.5 pb-2.5 border-b border-[#162234]">
                <div className="w-8 h-8 rounded-lg bg-[#141f30] border border-[#22344d] flex items-center justify-center text-sky-400 font-bold">
                  <User className="w-4 h-4" />
                </div>
                <div>
                  <p className="font-semibold text-slate-100">Bilton Neva</p>
                  <p className="text-[10px] text-slate-500">Investigador Forense</p>
                </div>
              </div>

              <div className="pt-2.5 space-y-2 text-[11px] text-slate-400">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Entorno:</span>
                  <span className="text-emerald-400">Laboratorio Local</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Modo:</span>
                  <span className="text-slate-300">Monousuario</span>
                </div>
                <p className="text-[10px] text-slate-500 leading-relaxed pt-1 border-t border-[#162234]">
                  <Info className="w-3 h-3 inline mr-1 text-sky-400" />
                  Sesión local activa. Las auditorías y grafos se almacenan en la base de datos local.
                </p>
              </div>
            </div>
          )}
        </div>
        */}
      </div>
    </header>
  );
}
