"use client";

import { BarChart3 } from "lucide-react";
import type { IdentityScoreDistribution } from "@/lib/types";

/**
 * Histograma de las probabilidades de atribución del modelo de identidad.
 *
 * Además de ser una figura reportable, funciona como diagnóstico: si las barras
 * se concentran en dos o tres valores, el modelo no está discriminando. Es
 * exactamente lo que ocurría antes de la reescritura del scorer, cuando las
 * señales sin dato se contaban como desacuerdo y toda la distribución colapsaba
 * en {0.05, 0.45, 0.95}.
 */

const CONFIRMED_THRESHOLD = 0.7;

export function ScoreDistribution({ data }: { data: IdentityScoreDistribution }) {
  if (!data || data.total_scored_entities === 0) {
    return (
      <div className="panel-card p-5">
        <Header />
        <p className="text-xs text-slate-400 mt-3 max-w-2xl leading-relaxed">
          Todavía no hay hallazgos puntuados con el modelo actual. Lanza una
          investigación para poblar la distribución.
        </p>
      </div>
    );
  }

  const max = Math.max(...data.buckets.map((b) => b.count), 1);
  const versions = Object.entries(data.scorer_versions);

  return (
    <div className="panel-card p-5 space-y-4">
      <Header />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Tile
          label="Hallazgos puntuados"
          value={data.total_scored_entities.toLocaleString("es-ES")}
          hint="Total de entidades con probabilidad de atribución calculada."
        />
        <Tile
          label="Atribuidos al objetivo"
          value={`${data.attributed_count} (${data.attributed_pct}%)`}
          hint={`Superan el umbral de decisión del ${CONFIRMED_THRESHOLD * 100}%.`}
          highlight
        />
        <Tile
          label="Valores distintos"
          value={String(data.distinct_values)}
          hint="Cuántas puntuaciones diferentes produce el modelo. Un número bajo indica que no discrimina: la versión anterior solo producía tres."
        />
      </div>

      {/* Histograma en deciles */}
      <div
        className="flex items-end gap-1 h-36 pt-2"
        role="img"
        aria-label={`Histograma de atribución: ${data.buckets
          .map((b) => `${Math.round(b.from * 100)}-${Math.round(b.to * 100)}%: ${b.count}`)
          .join("; ")}`}
      >
        {data.buckets.map((bucket) => {
          const attributed = bucket.from >= CONFIRMED_THRESHOLD;
          const heightPct = (bucket.count / max) * 100;
          return (
            <div key={bucket.from} className="flex-1 flex flex-col items-center gap-1 h-full">
              <div className="flex-1 w-full flex items-end">
                <div
                  title={`${Math.round(bucket.from * 100)}–${Math.round(
                    bucket.to * 100
                  )}% de atribución: ${bucket.count} hallazgo(s)`}
                  className={`w-full rounded-t transition-all ${
                    attributed ? "bg-emerald-400/70" : "bg-sky-500/30"
                  }`}
                  style={{ height: `${Math.max(heightPct, bucket.count > 0 ? 3 : 0)}%` }}
                />
              </div>
              <span className="text-[9px] font-mono text-slate-500 tabular-nums">
                {Math.round(bucket.from * 100)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-400 pt-1 border-t border-[#1e293b]">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-sky-500/30" aria-hidden="true" />
          Descartados o dudosos
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-2 rounded-sm bg-emerald-400/70" aria-hidden="true" />
          Atribuidos (≥ {CONFIRMED_THRESHOLD * 100}%)
        </span>
        {versions.length > 0 && (
          <span className="ml-auto font-mono">
            modelo{versions.length > 1 ? "s" : ""}:{" "}
            {versions.map(([v, n]) => `${v} (${n})`).join(" · ")}
          </span>
        )}
      </div>

      {versions.length > 1 && (
        <p className="text-[11px] text-amber-300/90 leading-snug">
          Hay hallazgos puntuados con versiones distintas del modelo. Sus
          probabilidades <strong>no son comparables entre sí</strong>: para un
          análisis agregado conviene volver a ejecutar las investigaciones
          antiguas o filtrarlas por versión.
        </p>
      )}
    </div>
  );
}

function Header() {
  return (
    <div className="flex items-start gap-2">
      <BarChart3 className="w-4 h-4 text-sky-400 mt-0.5 shrink-0" aria-hidden="true" />
      <div>
        <h3 className="text-sm font-semibold text-slate-100">
          Distribución de Probabilidad de Atribución
        </h3>
        <p className="text-xs text-slate-400 mt-0.5 max-w-2xl leading-relaxed">
          Para cada hallazgo, la probabilidad de que pertenezca a la persona
          investigada según el modelo Fellegi-Sunter. Es distinta de la certeza
          de que la cuenta exista.
        </p>
      </div>
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
  highlight = false,
}: {
  label: string;
  value: string;
  hint: string;
  highlight?: boolean;
}) {
  return (
    <div
      title={hint}
      className={`p-3 rounded-md border ${
        highlight ? "bg-emerald-500/10 border-emerald-500/30" : "bg-[#0c111a] border-[#1e293b]"
      }`}
    >
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div
        className={`text-lg font-bold font-mono mt-0.5 ${
          highlight ? "text-emerald-300" : "text-slate-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
