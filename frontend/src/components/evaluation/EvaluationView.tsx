"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Copy,
  Check,
  Download,
  BookOpen,
  Award,
} from "lucide-react";
import { getMetricsComparison, getSurveyStats } from "@/lib/api";
import type {
  EngineId,
  EngineMetrics,
  HybridContribution,
  MetricsComparison,
  SurveyStats,
} from "@/lib/types";

const EMPTY_METRICS: EngineMetrics = {
  count: 0,
  avg_execution_time: 0,
  avg_entities: 0,
  avg_clusters: 0,
};

const METRIC_ROWS: Array<{
  key: keyof EngineMetrics;
  label: string;
  hint: string;
  suffix?: string;
}> = [
  {
    key: "count",
    label: "Muestras analizadas",
    hint: "Investigaciones completadas con este motor (n)",
  },
  {
    key: "avg_execution_time",
    label: "Latencia media",
    hint: "Segundos de extremo a extremo.",
    suffix: "s",
  },
  {
    key: "avg_entities",
    label: "Entidades descubiertas",
    hint: "Media de hallazgos únicos por investigación",
  },
  {
    key: "avg_clusters",
    label: "Grupos de correlación",
    hint: "Media de agrupaciones conectadas por evidencia explícita.",
  },
];

export function EvaluationView() {
  const [data, setData] = useState<MetricsComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // NOTA: el cuestionario de concientización es hoy una maqueta sin estado ni
  // envío. Los antiguos `preTestScore`/`postTestScore` se declaraban y no se
  // leían nunca. Se cablea de verdad contra POST /api/v1/surveys en la Fase 1.
  const [showSurvey, setShowSurvey] = useState(false);

  const loadMetrics = useCallback(() => {
    setLoading(true);
    getMetricsComparison()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "No se pudieron cargar las métricas")
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => loadMetrics(), 0);
    return () => clearTimeout(initialLoad);
  }, [loadMetrics]);

  const handleCopyLatex = () => {
    if (!data?.latex_table) return;
    navigator.clipboard.writeText(data.latex_table);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportCsv = () => {
    if (!data?.investigations_sample) return;
    // `engine_used` va en su propia columna, aparte de `strategy`: son cosas
    // distintas, y confundirlas es lo que hacía que la comparativa contase como
    // agéntica una investigación que había ejecutado el motor de reglas.
    const headers = "id,strategy,engine_used,execution_time_seconds,entities_count,created_at\n";
    const rows = data.investigations_sample
      .map(
        (s) =>
          `${s.id},${s.strategy},${s.engine_used || ""},${s.execution_time},${s.entities_count},${s.created_at || ""}`
      )
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "osint_evaluation_metrics.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div role="status" className="panel-card p-12 text-center text-xs font-mono text-slate-400">
        Cargando métricas de evaluación científica...
      </div>
    );
  }

  // Sin esto, un fallo de red renderizaba el dashboard completo con todos los
  // valores a 0 y el bloque LaTeX vacío, sin ningún aviso: una pantalla titulada
  // "Módulo de Evaluación para Artículo Científico" mostrando cifras inventadas.
  if (error || !data) {
    return (
      <div className="panel-card p-10 text-center border border-rose-500/30">
        <AlertTriangle className="w-9 h-9 text-rose-400 mx-auto mb-3" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-slate-200">
          No se pudieron cargar las métricas de evaluación
        </h3>
        <p className="text-xs text-slate-400 mt-1.5 max-w-md mx-auto">
          {error || "El backend no devolvió datos."} Las cifras no se muestran para no
          presentar valores incorrectos como si fueran resultados reales.
        </p>
        <button
          type="button"
          onClick={loadMetrics}
          className="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors cursor-pointer"
        >
          Reintentar
        </button>
      </div>
    );
  }

  // Tres brazos experimentales, no dos. `hybrid` se añadió sin tocar los otros
  // dos precisamente para que la tabla del artículo pase de dos filas a tres sin
  // invalidar las mediciones ya tomadas.
  const engines: Array<{
    id: EngineId;
    label: string;
    tone: string;
    metrics: EngineMetrics;
  }> = [
    {
      id: "rules",
      label: data.engine_labels?.rules ?? "Motor por Reglas",
      tone: "text-sky-400",
      metrics: data.summary.rule_based ?? EMPTY_METRICS,
    },
    {
      id: "agentic",
      label: data.engine_labels?.agentic ?? "Agente IA Autónomo",
      tone: "text-purple-400",
      metrics: data.summary.agentic ?? EMPTY_METRICS,
    },
    {
      id: "hybrid",
      label: data.engine_labels?.hybrid ?? "Híbrido (Reglas + IA)",
      tone: "text-emerald-400",
      metrics: data.summary.hybrid ?? EMPTY_METRICS,
    },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[#1e293b]">
        <div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/20 text-purple-400 font-mono text-[11px] mb-1.5">
            <BookOpen className="w-3.5 h-3.5" />
            <span>Módulo de Evaluación para Artículo Científico</span>
          </div>
          <h2 className="text-base font-bold text-slate-100">
            Comparativa Experimental: Reglas vs. Agente Autónomo IA vs. Híbrido
          </h2>
          <p className="text-xs text-slate-400 mt-0.5 max-w-2xl">
            Métricas de cobertura, latencia y precisión para contrastar las tres aproximaciones
            metodológicas. Cada investigación se agrupa por el motor que{" "}
            <em>realmente</em> se ejecutó, no por la estrategia solicitada: sin LLM configurado,
            las estrategias que dependen de él degradan al motor de reglas y se contabilizan
            como tales.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopyLatex}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-sky-400" />}
            <span>{copied ? "¡Copiado a portapapeles!" : "Copiar Tabla LaTeX"}</span>
          </button>

          <button
            onClick={handleExportCsv}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors"
          >
            <Download className="w-3.5 h-3.5 text-sky-400" />
            <span>Exportar CSV</span>
          </button>
        </div>
      </div>

      {/* Tabla comparativa de los tres brazos experimentales.
          Antes eran cuatro tarjetas con dos cifras cada una ("12s / 34s"); con
          un tercer motor esa forma deja de leerse. Una tabla métrica × motor es
          además la forma exacta en la que el dato acaba en el artículo. */}
      <div className="panel-card overflow-hidden">
        <div className="px-5 py-3 border-b border-[#1e293b] flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-xs font-mono font-bold uppercase text-slate-300">
            Resultados por motor
          </h3>
          <span className="text-[11px] font-mono text-slate-400">
            {data.summary.total_investigations} investigación(es) completada(s)
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <caption className="sr-only">
              Comparativa de latencia, cobertura y exposición entre los tres motores de
              orquestación
            </caption>
            <thead className="bg-[#0c111a] text-[10px] font-mono uppercase tracking-wider text-slate-400 border-b border-[#1e293b]">
              <tr>
                <th scope="col" className="py-3 px-4">
                  Métrica
                </th>
                {engines.map((e) => (
                  <th key={e.id} scope="col" className={`py-3 px-4 text-right ${e.tone}`}>
                    {e.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#161f2e] text-xs font-mono text-slate-200">
              {METRIC_ROWS.map((row) => (
                <tr key={row.key} className="hover:bg-[#111826] transition-colors">
                  <th
                    scope="row"
                    title={row.hint}
                    className="py-2.5 px-4 font-normal text-slate-300 font-sans text-xs"
                  >
                    {row.label}
                  </th>
                  {engines.map((e) => (
                    <td key={e.id} className="py-2.5 px-4 text-right tabular-nums">
                      {e.metrics.count === 0 && row.key !== "count" ? (
                        <span className="text-slate-500" title="Sin muestras de este motor">
                          —
                        </span>
                      ) : (
                        `${e.metrics[row.key]}${row.suffix ?? ""}`
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Aportación específica del refinamiento por IA */}
      {data.hybrid_contribution && data.hybrid_contribution.investigations > 0 && (
        <HybridContributionPanel contribution={data.hybrid_contribution} />
      )}

      {/* LaTeX Preview Block */}

      <div className="panel-card p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-mono font-bold uppercase text-slate-300">
            Tabla LaTeX Generada Automáticamente (Para pegar en Overleaf)
          </h3>
          <button
            onClick={handleCopyLatex}
            className="text-xs font-mono text-sky-400 hover:underline flex items-center gap-1"
          >
            <Copy className="w-3 h-3" /> Copiar código
          </button>
        </div>
        <pre className="p-4 rounded bg-[#070a10] border border-[#1e293b] text-[11px] font-mono text-slate-300 overflow-x-auto selection:bg-sky-500 selection:text-white">
          {data?.latex_table}
        </pre>
      </div>

      {/* Social Experiment / Awareness Questionnaire Section */}
      <div className="panel-card p-6 border-l-4 border-l-purple-500">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
              <Award className="w-4 h-4 text-purple-400" />
              Medición de Concientización Estudiantil (Pre-Test vs. Post-Test)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Protocolo pedagógico para medir la variación en la percepción del riesgo antes y después de interactuar con person-map.
            </p>
          </div>

          <button
            onClick={() => setShowSurvey(!showSurvey)}
            className="text-xs font-mono px-3 py-1.5 rounded bg-[#182334] text-purple-300 border border-purple-500/30 hover:bg-[#202c40] transition-colors"
          >
            {showSurvey ? "Ocultar Cuestionario" : "Abrir Cuestionario Pedagógico"}
          </button>
        </div>

        {showSurvey && (
          <div className="mt-4 pt-4 border-t border-[#1e293b] animate-fade-in">
            <SurveyStatsPanel />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Qué aporta la capa de refinamiento por IA, en cifras.
 *
 * Es la pregunta que decide si la tercera condición experimental se justifica.
 * "El híbrido encuentra más" no es una afirmación defendible sin separar cuánto
 * puso el barrido heurístico y cuántas entidades existen únicamente porque el
 * LLM las pidió. Las llamadas descartadas miden lo contrario: cuánto trabajo
 * redundante propuso el modelo y el motor le ahorró al no repetirlo.
 */
function HybridContributionPanel({ contribution }: { contribution: HybridContribution }) {
  const share =
    contribution.avg_heuristic_findings + contribution.avg_refinement_findings > 0
      ? (contribution.avg_refinement_findings /
          (contribution.avg_heuristic_findings + contribution.avg_refinement_findings)) *
        100
      : 0;

  return (
    <div className="panel-card p-5 border-l-4 border-l-emerald-500">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
        <h3 className="text-sm font-bold text-slate-100">
          Aportación de la capa de refinamiento IA
        </h3>
        <span className="text-[11px] font-mono text-slate-400">
          sobre {contribution.investigations} investigación(es) híbrida(s)
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="Hallazgos capa 1"
          value={contribution.avg_heuristic_findings.toFixed(1)}
          hint="Media de hallazgos en bruto del barrido heurístico determinista"
        />
        <StatTile
          label="Hallazgos capa 2"
          value={contribution.avg_refinement_findings.toFixed(1)}
          hint="Media de hallazgos añadidos por las llamadas que pidió el LLM"
        />
        <StatTile
          label="Entidades solo de la IA"
          value={contribution.avg_entities_only_from_llm.toFixed(1)}
          hint="Entidades finales que ninguna herramienta del barrido llegó a descubrir. Es la aportación neta del refinamiento."
          highlight={contribution.avg_entities_only_from_llm > 0}
        />
        <StatTile
          label="Llamadas evitadas"
          value={String(contribution.refinement_calls_skipped)}
          hint="Llamadas que el LLM pidió repetir y el motor descartó porque el barrido ya las había ejecutado"
        />
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-[11px] font-mono mb-1.5">
          <span className="text-slate-300">Proporción de hallazgos aportados por la IA</span>
          <span className="font-bold text-slate-100">{share.toFixed(1)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-[#161f2e] overflow-hidden">
          <div
            className="h-full rounded-full bg-emerald-400"
            style={{ width: `${Math.min(100, Math.max(0, share))}%` }}
          />
        </div>
      </div>

    </div>
  );
}

/**
 * Resultados agregados del cuestionario de concientización.
 *
 * Antes aquí había una maqueta de tres preguntas con radios sin estado ni
 * envío. La captura se ha movido al informe de cada investigación (donde
 * ocurre el momento pedagógico) y esta pantalla, que es la orientada al
 * artículo, muestra el agregado.
 */
function SurveyStatsPanel() {
  const [stats, setStats] = useState<SurveyStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    getSurveyStats()
      .then((s) => {
        setStats(s);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "No se pudieron cargar las respuestas")
      )
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => load(), 0);
    return () => clearTimeout(initialLoad);
  }, [load]);

  if (loading) {
    return (
      <p role="status" className="text-xs font-mono text-slate-400">
        Cargando respuestas del cuestionario...
      </p>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-xs text-rose-300">
        <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
        <span>{error}</span>
        <button
          type="button"
          onClick={load}
          className="ml-2 underline hover:text-rose-200 cursor-pointer"
        >
          Reintentar
        </button>
      </div>
    );
  }

  if (!stats || stats.total_responses === 0) {
    return (
      <p className="text-xs text-slate-400 leading-relaxed max-w-2xl">
        Todavía no hay respuestas. El cuestionario se contesta al final del{" "}
        <span className="text-slate-200 font-semibold">
          Informe de Concientización
        </span>{" "}
        de cada investigación, justo después de que la persona ve su propia huella
        digital. El delta pre/post que se agrega aquí es la métrica pedagógica del
        estudio.
      </p>
    );
  }

  const delta = stats.delta_awareness;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="Respuestas"
          value={String(stats.total_responses)}
          hint="Tamaño de muestra (n)"
        />
        <StatTile
          label="Percepción previa"
          value={stats.avg_pre_awareness.toFixed(2)}
          hint="Media de exposición percibida ANTES de ver el expediente (escala 1-5)"
        />
        <StatTile
          label="Percepción posterior"
          value={stats.avg_post_awareness.toFixed(2)}
          hint="Media DESPUÉS de ver el expediente (escala 1-5)"
        />
        <StatTile
          label="Delta de concienciación"
          value={`${delta > 0 ? "+" : ""}${delta.toFixed(2)}`}
          hint="Diferencia post - pre. Es la variable dependiente del estudio."
          highlight={delta > 0}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
        <PctBar
          label="Reutiliza el mismo alias"
          pct={stats.reused_alias_pct}
          tone="bg-amber-400"
        />
        <PctBar
          label="Ignoraba la fuga por commits"
          pct={stats.ignorant_commit_leak_pct}
          tone="bg-rose-400"
        />
        <PctBar
          label="Cambiará sus hábitos"
          pct={stats.will_change_habits_pct}
          tone="bg-emerald-400"
        />
      </div>
    </div>
  );
}

function StatTile({
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
      className={`p-3.5 rounded-md border ${
        highlight
          ? "bg-emerald-500/10 border-emerald-500/30"
          : "bg-[#0c111a] border-[#1e293b]"
      }`}
    >
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div
        className={`text-xl font-bold font-mono mt-1 ${
          highlight ? "text-emerald-300" : "text-slate-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function PctBar({ label, pct, tone }: { label: string; pct: number; tone: string }) {
  return (
    <div className="p-3.5 rounded-md bg-[#0c111a] border border-[#1e293b]">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-slate-300">{label}</span>
        <span className="font-mono font-bold text-slate-100">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-[#161f2e] overflow-hidden">
        <div
          className={`h-full rounded-full ${tone}`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
    </div>
  );
}
