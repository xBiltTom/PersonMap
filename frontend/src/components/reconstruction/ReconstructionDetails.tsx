import type { DigitalFootprintReconstruction } from "../../lib/types";
import { reconstructionDetails, type GraphSelection } from "../../lib/reconstructionState.ts";

export function ReconstructionDetails({ snapshot, selection }: {
  snapshot: DigitalFootprintReconstruction; selection: GraphSelection;
}) {
  const details = reconstructionDetails(snapshot, selection);
  if (!details) return <aside className="reconstruction-details" aria-label="Detalles de evidencia">
    <h3>¿Por qué está aquí?</h3><p>Selecciona un nodo o una relación para ver su base y evidencia.</p>
  </aside>;
  const { item, evidence } = details;
  return <aside className="reconstruction-details" aria-label="Detalles de evidencia" aria-live="polite">
    <h3>{"label" in item ? item.label : item.type.replaceAll("_", " ")}</h3>
    <span className="reconstruction-basis">{item.basis}</span>
    {"kind" in item ? <>
      <p>{item.platform || item.kind}</p><p>{item.safe_summary}</p>
      {item.ownership_basis && <p>Atribución: {item.ownership_basis === "subject_declared" ? "declarada por el sujeto" : "confirmada por el sujeto"}.</p>}
      {item.source_tools.length > 0 && <p>Encontrado por: {item.source_tools.join(", ")}</p>}
      {item.severity && <p>Impacto potencial del hallazgo: {item.severity}</p>}
      {item.url && <a href={item.url} target="_blank" rel="noreferrer">Abrir fuente ↗</a>}
    </> : <p>{item.why}</p>}
    <h4>{item.evidence_count} referencias · {item.evidence_types.join(", ")}</h4>
    <ul>{evidence.map(ref => <li key={ref.id}>
      <p>{ref.excerpt}</p>{ref.platform && <small>{ref.platform}</small>}
      {ref.url && <a href={ref.url} target="_blank" rel="noreferrer">Ver evidencia ↗</a>}
    </li>)}</ul>
  </aside>;
}
