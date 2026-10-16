import { fairCoverage } from "../../lib/fairCoverage.ts";

export function FairCoverage({ metrics }: { metrics: Record<string, unknown> }) {
  return <section className="panel-card p-4 space-y-3" aria-label="Cobertura de fuentes Lite">
    <h2 className="text-sm font-semibold text-sky-200">Fuentes de la búsqueda Lite</h2>
    <p className="text-xs text-slate-400">Las fuentes trabajan de forma independiente. Una fuente sin respuesta no implica que no exista información pública.</p>
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {fairCoverage(metrics).map(source => <article key={source.key} className="rounded border border-slate-700/50 p-3">
        <h3 className="text-xs font-semibold text-slate-200">{source.label}</h3>
        <p className="text-xs mt-2 text-sky-300">{source.statusLabel} · {source.count} hallazgos</p>
        {source.note && <p className="text-xs mt-1 text-slate-400">{source.note}</p>}
      </article>)}
    </div>
  </section>;
}
