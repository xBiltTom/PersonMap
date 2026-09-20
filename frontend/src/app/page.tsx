import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  FileSearch,
  FolderOpen,
  Network,
  ScanSearch,
  Waypoints,
} from "lucide-react";

const modules = [
  {
    title: "Nueva auditoría",
    description: "Registra datos conocidos y define el motor de exploración para iniciar una investigación.",
    icon: ScanSearch,
    href: "/auditorias/nueva",
  },
  {
    title: "Expedientes",
    description: "Consulta auditorías guardadas, su estado operativo y el acceso directo a cada caso.",
    icon: FolderOpen,
    href: "/expedientes",
  },
  {
    title: "Mapa digital",
    description: "Explora observaciones y relaciones documentadas dentro de un expediente concreto.",
    icon: Network,
    href: "/expedientes",
  },
];

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <section className="relative overflow-hidden rounded-xl border border-[#20344c] bg-[#0b1421] px-5 py-7 sm:px-8 sm:py-9">
        <div className="pointer-events-none absolute -right-20 top-0 h-56 w-56 rounded-full border border-cyan-400/10" />
        <div className="pointer-events-none absolute -right-8 top-12 h-32 w-32 rounded-full border border-violet-400/10" />
        <div className="relative max-w-3xl">
          <h1 className="max-w-2xl text-2xl font-semibold tracking-tight text-slate-100 sm:text-3xl">
            Observa la huella pública. Conserva el contexto. Decide con evidencia.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400">
            PersonMap organiza hallazgos públicos para una auditoría de huella digital. Reúne observaciones,
            fuentes y relaciones documentadas para que la revisión final siga siendo humana.
          </p>
          <div className="mt-6 flex flex-wrap gap-2.5">
            <Link href="/auditorias/nueva" className="inline-flex items-center gap-2 rounded-md border border-sky-400/45 bg-sky-500/15 px-3 py-2 font-mono text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/25">
              Iniciar nueva auditoría <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link href="/expedientes" className="inline-flex items-center gap-2 rounded-md border border-[#2a415d] bg-[#101d2e] px-3 py-2 font-mono text-xs text-slate-300 transition-colors hover:border-[#3d5d80] hover:text-slate-100">
              Ver expedientes <FolderOpen className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(260px,0.75fr)]">
        <div className="panel-card border border-[#1c3046] bg-[#0b121d] p-5 sm:p-6">
          <div className="flex items-center gap-2 text-cyan-200">
            <Waypoints className="h-4 w-4" />
            <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em]">Alcance de una auditoría</h2>
          </div>
          <div className="mt-5 grid gap-px overflow-hidden rounded-lg border border-[#1c3046] bg-[#1c3046] sm:grid-cols-4">
            {[
              ["Punto de partida", "Datos aportados de forma explícita."],
              ["Observaciones", "Recursos públicos encontrados."],
              ["Relaciones", "Evidencia y procedencia documentadas."],
              ["Revisión humana", "Interpretación final del analista."],
            ].map(([title, description]) => (
              <div key={title} className="bg-[#0b121d] p-3.5">
                <p className="font-mono text-[10px] text-cyan-200">{title}</p>
                <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{description}</p>
              </div>
            ))}
          </div>
        </div>

        <aside className="rounded-xl border border-violet-400/15 bg-violet-500/[0.04] p-5">
          <div className="flex items-center gap-2 text-violet-200">
            <BookOpen className="h-4 w-4" />
            <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em]">Límite metodológico</h2>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-slate-400">
            PersonMap no confirma que una cuenta pertenezca a una persona ni asigna porcentajes de identidad.
            Presenta evidencia observada y sus fuentes para una validación responsable.
          </p>
        </aside>
      </section>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <FileSearch className="h-4 w-4 text-sky-400" />
          <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300">Módulos de trabajo</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {modules.map((module) => {
            const Icon = module.icon;
            return (
              <Link key={module.title} href={module.href} className="group rounded-lg border border-[#1b2b40] bg-[#0b121d] p-4 transition-colors hover:border-sky-500/35 hover:bg-[#0e1927]">
                <Icon className="h-4 w-4 text-sky-400" />
                <h3 className="mt-3 text-sm font-medium text-slate-200 group-hover:text-sky-100">{module.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{module.description}</p>
              </Link>
            );
          })}
        </div>
      </section>
    </div>
  );
}
