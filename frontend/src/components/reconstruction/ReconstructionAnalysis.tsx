"use client";

import { useState } from "react";
import type { DigitalFootprintReconstruction, ExposureSeverity } from "../../lib/types";

const severityLabels: Record<ExposureSeverity, string> = {
  high: "Alto", medium: "Medio", low: "Bajo", informational: "Informativo",
};

export function ReconstructionAnalysis({ snapshot }: { snapshot: DigitalFootprintReconstruction }) {
  const [filter, setFilter] = useState("all");
  const [platform, setPlatform] = useState("all");
  const [limit, setLimit] = useState(10);
  const facts = new Map(snapshot.facts.map(fact => [fact.id, fact]));
  const assessments = snapshot.post_assessments ?? [];
  const risky = assessments.filter(item => item.signals.length > 0);
  const platforms = [...new Set(assessments.map(item => facts.get(item.fact_id)?.platform).filter(
    (value): value is string => !!value))].sort();
  const visible = assessments.filter(item => (filter === "all" || item.severity === filter || item.status === filter)
    && (platform === "all" || facts.get(item.fact_id)?.platform === platform));
  const firstRisk = risky.find(item => item.severity === "high" || item.severity === "medium");

  return <>
    <section className="reconstruction-panel" aria-label="Identidad reconstruida">
      <h2>Lo que tu huella permite reconstruir</h2>
      <p>Datos declarados, observaciones y conexiones entre fuentes confirmadas. Cada afirmación muestra los hechos que la sostienen.</p>
      {snapshot.identity_portrait?.map(claim => <details className="reconstruction-claim" key={claim.fact_ids.join(":") + claim.text}>
        <summary>{claim.text}</summary>
        {claim.basis && <p><strong>{claim.basis === "CORRELATED" ? "Conexión entre fuentes" : "Observación directa"}</strong></p>}
        {claim.caveat && <p><strong>Alcance:</strong> {claim.caveat}</p>}
        {claim.evidence_refs?.map(ref => snapshot.evidence[ref] && <blockquote className="reconstruction-evidence" key={ref}>
          “{snapshot.evidence[ref].excerpt}”
        </blockquote>)}
        <ul>{claim.fact_ids.map(id => {
          const fact = facts.get(id);
          return fact ? <li key={id}><strong>{fact.label}</strong> <span className="reconstruction-basis">{fact.basis}</span>
            {fact.url && <> · <a href={fact.url} target="_blank" rel="noreferrer">Ver fuente ↗</a></>}
          </li> : null;
        })}</ul>
      </details>)}
      {!snapshot.identity_portrait?.length && <p>Reconstruye la huella para obtener la síntesis de identidad con las evidencias disponibles.</p>}
    </section>

    <section className="reconstruction-panel" aria-label="Análisis de publicaciones">
      <h2>Qué publicaciones requieren tu atención</h2>
      <p>{assessments.length} publicaciones registradas · {risky.length} con señales detectadas · {assessments.filter(item => item.status === "no_text").length} sin texto evaluable.</p>
      <p>Ordenadas por exposición potencial. El análisis considera el propósito de la publicación, su antigüedad y si la cuenta figura como colaboradora. {snapshot.analysis_provider === "mcp"
        ? "Incluye las imágenes que el agente declara haber inspeccionado; una miniatura no equivale a analizar el video o audio completo."
        : "Imágenes, audio y video quedan fuera de esta lectura."}</p>
      {snapshot.coverage_reasons.includes("visual_media_not_inspected") && <p role="status">Hay imágenes disponibles que el agente no declaró haber inspeccionado. La cobertura visual es parcial.</p>}
      {snapshot.content_analysis_status !== "completed" && <p role="status">{snapshot.content_analysis_status === "partial"
        ? "La lectura contextual se completó para algunas publicaciones; las demás conservan la revisión por reglas."
        : "Lectura contextual no disponible. Se muestran señales preliminares de la revisión por reglas."}</p>}
      {firstRisk && <aside className="reconstruction-priority" data-severity={firstRisk.severity}>
        <strong>Empieza por esta publicación · {severityLabels[firstRisk.severity!]}</strong>
        <p>{firstRisk.explanation}</p>
        <a href={`#post-${firstRisk.fact_id}`} onClick={() => { setFilter("all"); setPlatform("all"); setLimit(10); }}>Ver evidencia y acciones ↓</a>
      </aside>}
      <div className="reconstruction-analysis-filters">
        <label>Riesgo o estado<select value={filter} onChange={event => { setFilter(event.target.value); setLimit(10); }}>
          <option value="all">Todas las publicaciones</option>
          {Object.entries(severityLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
          <option value="no_signals">Sin señales detectadas</option>
          <option value="no_text">Sin texto evaluable</option>
          <option value="not_analyzed">Sin analizar</option>
        </select></label>
        <label>Plataforma<select value={platform} onChange={event => { setPlatform(event.target.value); setLimit(10); }}>
          <option value="all">Todas las plataformas</option>
          {platforms.map(value => <option value={value} key={value}>{value}</option>)}
        </select></label>
      </div>
      <p role="status">{visible.length} publicaciones coinciden con los filtros.</p>
      <ol className="reconstruction-posts">{visible.slice(0, limit).map(item => {
        const fact = facts.get(item.fact_id);
        if (!fact) return null;
        return <li key={item.fact_id} id={`post-${item.fact_id}`} className="reconstruction-post" data-severity={item.severity ?? "none"}>
          <header><h3>{item.title || `${fact.platform || "Fuente pública"} · ${fact.label}`}</h3>
            <span className="reconstruction-basis">{item.severity ? severityLabels[item.severity] : item.status === "no_text" ? "Sin texto" : item.status === "not_analyzed" ? "Sin analizar" : "Sin señales"}</span>
          </header>
          <p>{fact.platform || "Fuente pública"} · {fact.date && <time dateTime={fact.date}>{fact.date}</time>}
            {snapshot.correlations.some(relation => relation.type === "COAUTHORED" && relation.target === item.fact_id) && " · Publicación colaborativa"}
          </p>
          {item.context && <p><strong>Qué cuenta este post:</strong> {item.context}</p>}
          <p><strong>Evaluación:</strong> {item.explanation}</p>
          {fact.url && <a href={fact.url} target="_blank" rel="noreferrer">Abrir publicación original ↗</a>}
          {!!item.signals.length && <details open={item.fact_id === firstRisk?.fact_id}>
            <summary>{item.signals.length} señales · evidencia, impacto y acciones</summary>
            {item.signals.map(signal => <section className="reconstruction-risk-signal" key={signal.category}>
              <h4>{signal.label} · {severityLabels[signal.severity]}</h4>
              <p><strong>Qué se observó:</strong> {signal.observation}</p>
              <p><strong>Por qué te expone:</strong> {signal.why_it_matters}</p>
              <small>{item.analysis_method === "mcp" ? "Interpretación del agente recibida por MCP" : item.analysis_method === "ai" ? "Lectura contextual con cita verificada en el texto" : signal.analysis_method === "ai" ? "Clasificación de Exposure Lens" : "Señal detectada por reglas locales"}</small>
              {signal.evidence_refs.map(ref => snapshot.evidence[ref] && <blockquote className="reconstruction-evidence" key={ref}>
                {snapshot.evidence[ref].source_type === "mcp_visual_observation" && <small>Observación visual del agente · </small>}
                “{snapshot.evidence[ref].excerpt}”
              </blockquote>)}
            </section>)}
          </details>}
          {!!item.limitations?.length && <section className="reconstruction-risk-signal">
            <h4>Qué no permite concluir</h4>
            <ul className="reconstruction-recommendations">{item.limitations.map(text => <li key={text}>{text}</li>)}</ul>
          </section>}
          {!!item.recommendations.length && <section className="reconstruction-risk-signal">
            <h4>Qué puedes hacer con esta publicación</h4>
            <ul className="reconstruction-recommendations">{item.recommendations.map(rec => <li key={rec}>{rec}</li>)}</ul>
          </section>}
        </li>;
      })}</ol>
      {!assessments.length && <p>No hay publicaciones evaluadas en esta reconstrucción. Actualiza para incorporar el análisis disponible.</p>}
      {visible.length > limit && <button type="button" onClick={() => setLimit(current => current + 10)}>Mostrar 10 más</button>}
    </section>
  </>;
}
