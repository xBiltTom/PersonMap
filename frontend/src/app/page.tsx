import { InvestigationForm } from "@/components/investigation/InvestigationForm";
import { InvestigationHistory } from "@/components/investigation/InvestigationHistory";
import { Shield, Eye, Network, BookOpen } from "lucide-react";

export default function HomePage() {
  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Editorial Forensic Header */}
      <section className="relative">
        <div className="max-w-3xl">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-sky-500/10 border border-sky-500/20 text-sky-400 font-mono text-xs mb-3">
            <Shield className="w-3.5 h-3.5" />
            <span>Laboratorio de Seguridad de la Información // Ciclo VIII</span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-100 font-sans">
            Mapeo de Identidad & Huella Digital Pública
          </h1>

          <p className="mt-2.5 text-xs sm:text-sm text-slate-400 leading-relaxed max-w-2xl font-sans">
            Herramienta forense de fuentes abiertas (OSINT) diseñada para auditar la exposición digital
            de estudiantes. Extrae, correlaciona y comprueba la coherencia entre correos institucionales,
            alias, plataformas de desarrollo, repositorios académicos y redes sociales mediante
            reconocimiento heurístico determinista y agentes IA adaptativos.
          </p>

          <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-xs font-mono text-slate-300">
            <div className="p-2.5 rounded-lg bg-[#0d1420] border border-[#162234] flex items-center gap-2">
              <Eye className="w-4 h-4 text-sky-400 shrink-0" />
              <span className="text-[11px]">3,000+ Catálogos Heurísticos</span>
            </div>
            <div className="p-2.5 rounded-lg bg-[#0d1420] border border-[#162234] flex items-center gap-2">
              <Network className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="text-[11px]">Resolución vs Homónimos</span>
            </div>
            <div className="p-2.5 rounded-lg bg-[#0d1420] border border-[#162234] flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-purple-400 shrink-0" />
              <span className="text-[11px]">Concientización y Autodefensa</span>
            </div>
          </div>
        </div>
      </section>

      {/* Main Section: Form & History */}
      <div className="space-y-8">
        <section>
          <InvestigationForm />
        </section>

        <section>
          <InvestigationHistory />
        </section>
      </div>
    </div>
  );
}
