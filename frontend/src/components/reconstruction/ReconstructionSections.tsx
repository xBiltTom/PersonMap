import type { DigitalFootprintReconstruction } from "../../lib/types";

export function ReconstructionSections({ snapshot }: { snapshot: DigitalFootprintReconstruction }) {
  const facts = new Map(snapshot.facts.map(f => [f.id, f]));
  const sections = [
    ["declared", "Datos declarados"], ["accounts", "Cuentas atribuidas"],
    ["public_identifiers", "Identificadores públicos"], ["academic_presence", "Presencia académica y profesional"],
    ["documents", "Documentos y publicaciones"], ["breach_exposure", "Exposición en brechas"],
  ] as const;
  return <>
    {snapshot.coverage === "partial" && <aside role="status" className="reconstruction-notice">
      <strong>Cobertura parcial</strong><p>Esta reconstrucción representa únicamente las fuentes observadas durante esta investigación.</p>
    </aside>}
    <section aria-label="Resumen factual" className="reconstruction-panel">
      <h2>La huella reconstruible</h2>
      {snapshot.summary.map(claim => <p key={claim.text} data-fact-count={claim.fact_ids.length}>{claim.text}</p>)}
    </section>
    <div className="reconstruction-sections">
      {sections.map(([key, title]) => <section className="reconstruction-panel" key={key}>
        <h2>{title} <small>{snapshot.identity[key].length}</small></h2>
        {key === "breach_exposure" && <p>Exposición observada ≠ prueba de identidad. No modifica la atribución de cuentas.</p>}
        {!snapshot.identity[key].length && <p>Sin elementos representados en esta cobertura.</p>}
        <ul>{snapshot.identity[key].map(id => {
          const fact = facts.get(id);
          return fact && <li key={id}>
            <strong>{fact.label}</strong> <span className="reconstruction-basis">{fact.basis}</span>
            {fact.safe_summary && <p>{fact.safe_summary}</p>}
            {fact.source_tools.length > 0 && <small>Fuentes: {fact.source_tools.join(", ")}</small>}
            {fact.url && <a href={fact.url} target="_blank" rel="noreferrer">Abrir fuente ↗</a>}
          </li>;
        })}</ul>
      </section>)}
    </div>
    <section className="reconstruction-panel" aria-label="Contenido por plataforma">
      <h2>Contenido público observado</h2>
      <ul>{Object.entries(snapshot.content_by_platform).map(([platform, count]) =>
        <li key={platform}><strong>{platform}</strong> · {count} publicaciones o repositorios observados</li>)}</ul>
      {!Object.keys(snapshot.content_by_platform).length && <p>Sin contenido público representado.</p>}
    </section>
    <section className="reconstruction-panel" aria-label="Timeline pública">
      <h2>Eventos públicos observados</h2>
      <p>Fechas de publicaciones individuales; sin inferir patrones.</p>
      <ol className="reconstruction-timeline">{snapshot.timeline.map(event => <li key={event.id}>
        <time dateTime={event.date}>{event.date}</time><span>{event.label} · {event.platform || event.kind}</span>
        <small>{event.basis}</small>
      </li>)}</ol>
      {!snapshot.timeline.length && <p>No hay eventos con fecha pública verificable.</p>}
    </section>
  </>;
}
