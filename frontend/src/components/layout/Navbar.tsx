"use client";

import Link from "next/link";
import { Shield, Radio, Layers } from "lucide-react";
import { useEffect, useState } from "react";

export function Navbar() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/health")
      .then((res) => res.json())
      .then((data) => setBackendOnline(data.status === "healthy"))
      .catch(() => setBackendOnline(false));
  }, []);

  return (
    <header className="border-b border-[#1e293b] bg-[#0b0f17]/95 sticky top-0 z-50 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-9 h-9 rounded-lg bg-[#151d2c] border border-[#233044] flex items-center justify-center text-sky-400 group-hover:border-sky-500/50 transition-colors">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-sm tracking-wider text-slate-100">
                PERSON-MAP
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                OSINT v1.0
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-mono tracking-tight">
              Investigación y Reconstrucción de Huella Digital
            </p>
          </div>
        </Link>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#121824] border border-[#1e293b] text-xs font-mono">
            <Radio
              className={`w-3.5 h-3.5 ${
                backendOnline === true
                  ? "text-emerald-400 animate-pulse"
                  : backendOnline === false
                  ? "text-rose-500"
                  : "text-amber-400"
              }`}
            />
            <span className="text-slate-300">
              {backendOnline === true
                ? "Motor OSINT Activo"
                : backendOnline === false
                ? "Backend Offline (:8000)"
                : "Conectando..."}
            </span>
          </div>

          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs font-mono px-3 py-1.5 rounded-md bg-[#182234] hover:bg-[#202c42] text-slate-200 border border-[#2b3a52] transition-colors"
          >
            <Layers className="w-3.5 h-3.5 text-sky-400" />
            <span>Investigaciones</span>
          </Link>

          <Link
            href="/evaluation"
            className="flex items-center gap-1.5 text-xs font-mono px-3 py-1.5 rounded-md bg-purple-950/40 hover:bg-purple-900/50 text-purple-200 border border-purple-500/30 transition-colors"
          >
            <span>Métricas Paper</span>
          </Link>
        </div>
      </div>
    </header>
  );
}
