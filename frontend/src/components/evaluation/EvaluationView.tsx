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
import type { MetricsComparison, SurveyStats } from "@/lib/types";
import { ScoreDistribution } from "@/components/evaluation/ScoreDistribution";

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
    loadMetrics();
  }, [loadMetrics]);

  const handleCopyLatex = () => {
    if (!data?.latex_table) return;
    navigator.clipboard.writeText(data.latex_table);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExportCsv = () => {
    if (!data?.investigations_sample) return;
    const headers = "id,strategy,execution_time_seconds,entities_count,risk_score,created_at\n";
    const rows = data.investigations_sample
      .map(
        (s) =>
          `${s.id},${s.strategy},${s.execution_time},${s.entities_count},${s.risk_score},${s.created_at || ""}`
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

  const rb = data?.summary.rule_based || { count: 0, avg_execution_time: 0, avg_entities: 0, avg_clusters: 0, avg_risk_score: 0 };
  const ag = data?.summary.agentic || { count: 0, avg_execution_time: 0, avg_entities: 0, avg_clusters: 0, avg_risk_score: 0 };

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
            Comparativa Experimental: Motor por Reglas vs. Agente Autónomo IA
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Métricas de cobertura, latencia y precisión para contrastar ambas aproximaciones metodológicas.
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

      {/* Comparative Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Metric 1: Muestras */}
        <div className="panel-card p-4">
          <span className="text-[10px] font-mono uppercase text-slate-500 block mb-1">Muestras Totales</span>
          <div className="text-2xl font-bold font-mono text-slate-100">{data?.summary.total_investigations || 0}</div>
          <div className="flex justify-between text-[11px] font-mono mt-2 pt-2 border-t border-[#1e293b]">
            <span className="text-sky-400">Reglas: {rb.count}</span>
            <span className="text-purple-400">Agente: {ag.count}</span>
          </div>
        </div>

        {/* Metric 2: Tiempo de Ejecución */}
        <div className="panel-card p-4">
          <span className="text-[10px] font-mono uppercase text-slate-500 block mb-1">Latencia Media</span>
          <div className="text-2xl font-bold font-mono text-slate-100">
            {rb.avg_execution_time || ag.avg_execution_time ? `${rb.avg_execution_time}s / ${ag.avg_execution_time}s` : "0s"}
          </div>
          <div className="flex justify-between text-[11px] font-mono mt-2 pt-2 border-t border-[#1e293b]">
            <span className="text-sky-400">Reglas: {rb.avg_execution_time}s</span>
            <span className="text-purple-400">Agente: {ag.avg_execution_time}s</span>
          </div>
        </div>

        {/* Metric 3: Entidades Promedio */}
        <div className="panel-card p-4">
          <span className="text-[10px] font-mono uppercase text-slate-500 block mb-1">Entidades Descubiertas</span>
          <div className="text-2xl font-bold font-mono text-slate-100">
            {rb.avg_entities || ag.avg_entities ? `${rb.avg_entities} vs ${ag.avg_entities}` : "0"}
          </div>
          <div className="flex justify-between text-[11px] font-mono mt-2 pt-2 border-t border-[#1e293b]">
            <span className="text-sky-400">Reglas: {rb.avg_entities}</span>
            <span className="text-purple-400">Agente: {ag.avg_entities}</span>
          </div>
        </div>

        {/* Metric 4: Score de Riesgo */}
        <div className="panel-card p-4">
          <span className="text-[10px] font-mono uppercase text-slate-500 block mb-1">Exposición Promedio</span>
          <div className="text-2xl font-bold font-mono text-slate-100">
            {rb.avg_risk_score || ag.avg_risk_score ? `${rb.avg_risk_score}/100` : "0"}
          </div>
          <div className="flex justify-between text-[11px] font-mono mt-2 pt-2 border-t border-[#1e293b]">
            <span className="text-sky-400">Reglas: {rb.avg_risk_score}</span>
            <span className="text-purple-400">Agente: {ag.avg_risk_score}</span>
          </div>
        </div>
      </div>

      {/* LaTeX Preview Block */}
      {data.identity_score_distribution && (
        <ScoreDistribution data={data.identity_score_distribution} />
      )}

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
    load();
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
