export const FAIR_SOURCE_LABELS: Record<string, string> = {
  search_dorker: "Búsqueda web · SearchDorker", apify_social: "Contenido social · Apify",
  academic_finder: "Academia · OpenAlex / Crossref", username_finder: "Redes y foros",
  github_deep_scanner: "GitHub", social_verifier: "Verificación de perfiles",
  infostealer_checker: "Registros de infostealers", email_enumerator: "Enumeración de correo",
  google_account_osint: "Google público complementario",
  breach_checker: "Registros de brechas", ghunt: "Fuentes públicas de Google",
};
const STATUS: Record<string, string> = {
  pending: "Pendiente", running: "Buscando", completed: "Terminada", partial: "Cobertura parcial",
  timeout: "Tiempo agotado", skipped: "Omitida", budget_exhausted: "Cuota alcanzada",
  provider_unavailable: "Proveedor no disponible", not_applicable: "Sin datos compatibles", failed: "Falló la consulta",
};
export function fairCoverage(metrics: Record<string, unknown>) {
  const state = (metrics.fair_snapshot || metrics.fair_progress) as {
    sources?: Record<string, { status: string; findings_count: number; reason?: string }>;
  } | undefined;
  return Object.entries(FAIR_SOURCE_LABELS).map(([key, label]) => {
    const source = state?.sources?.[key];
    const status = source?.status || "pending";
    const note = source?.reason === "subject_consent_required" ? "Requiere autorizar la consulta externa de infostealers." : status === "not_applicable" ? (key === "academic_finder" ? "Necesita nombre completo, ORCID o DOI observado." : "No hay entradas compatibles para esta fuente.") :
      status === "provider_unavailable" ? "El proveedor o sus credenciales no están disponibles." :
      status === "budget_exhausted" ? "Se respetó el límite de consultas o coste." :
      status === "timeout" ? "No respondió dentro del presupuesto; no indica ausencia de datos." :
      status === "completed" && !source?.findings_count ? "La consulta no devolvió hallazgos en esta cobertura." : "";
    return { key, label, status, statusLabel: STATUS[status] || "Sin cobertura", count: source?.findings_count || 0, note };
  });
}
