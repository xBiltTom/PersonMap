"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  Copy,
  Check,
  Download,
  BookOpen,
  HelpCircle,
  Award,
  Sparkles,
  Workflow,
  Cpu,
} from "lucide-react";

interface ComparisonData {
  summary: {
    total_investigations: number;
    rule_based: {
      count: number;
      avg_execution_time: number;
      avg_entities: number;
      avg_clusters: number;
      avg_risk_score: number;
    };
    agentic: {
      count: number;
      avg_execution_time: number;
      avg_entities: number;
      avg_clusters: number;
      avg_risk_score: number;
    };
  };
  latex_table: string;
  investigations_sample: Array<{
    id: string;
    strategy: string;
    execution_time: number;
    entities_count: number;
    risk_score: number;
    created_at: string | null;
  }>;
}

export function EvaluationView() {
  const [data, setData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  // Pre-test / Post-test state for educational evaluation
  const [preTestScore, setPreTestScore] = useState<number | null>(null);
  const [postTestScore, setPostTestScore] = useState<number | null>(null);
  const [showSurvey, setShowSurvey] = useState(false);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/investigations/metrics/comparison")
      .then((res) => res.json())
      .then((d) => setData(d))
      .catch((err) => console.error("Error loading comparison metrics", err))
      .finally(() => setLoading(false));
  }, []);

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
      <div className="panel-card p-12 text-center text-xs font-mono text-slate-500">
        Cargando métricas de evaluación científica...
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
          <div className="mt-4 pt-4 border-t border-[#1e293b] space-y-4 animate-in fade-in duration-200 text-xs">
            <div className="p-3.5 rounded bg-[#0c111a] border border-[#1e293b] space-y-2">
              <span className="font-semibold text-slate-200 block">
                1. ¿Creías que tu correo universitario o personal era inaccesible si no lo publicabas en tu bio?
              </span>
              <div className="flex gap-3 text-slate-400 font-mono">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q1" /> Sí, creía que era privado
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q1" /> No, sabía que los commits git lo revelan
                </label>
              </div>
            </div>

            <div className="p-3.5 rounded bg-[#0c111a] border border-[#1e293b] space-y-2">
              <span className="font-semibold text-slate-200 block">
                2. ¿Reutilizas el mismo alias de usuario en cuentas académicas, de ocio y redes sociales?
              </span>
              <div className="flex gap-3 text-slate-400 font-mono">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q2" /> Sí, en la mayoría de servicios
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q2" /> No, mantengo identidades separadas
                </label>
              </div>
            </div>

            <div className="p-3.5 rounded bg-[#0c111a] border border-[#1e293b] space-y-2">
              <span className="font-semibold text-slate-200 block">
                3. Tras visualizar tu mapa digital y las recomendaciones, ¿modificarás tus hábitos de privacidad?
              </span>
              <div className="flex gap-3 text-slate-400 font-mono">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q3" /> Sí, cambiaré alias y activaré 2FA
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="radio" name="q3" /> No considero necesario cambiar nada
                </label>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
