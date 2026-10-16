import type { HealthStatus } from "../../lib/types";

export function LiteSearchInfo({ plan }: { plan: NonNullable<HealthStatus["lite_plan"]> }) {
  return <aside className="rounded-lg border border-sky-500/25 bg-sky-500/5 p-4 space-y-2" aria-label="Búsqueda Lite automática">
    <h3 className="text-sm font-semibold text-sky-200">Búsqueda Lite automática</h3>
    <p className="text-xs text-slate-300">Redes, comunidades y portafolios por prioridad: {plan.platforms.join(", ")}. Sin configurar herramientas ni alcances de escaneo.</p>
    <p className="text-xs text-slate-400">Búsqueda web y académica en paralelo. Añade nombre y apellidos para buscar autores y publicaciones en OpenAlex y Crossref.</p>
    <p className="text-xs text-slate-400">Las cuentas declaradas de Instagram, TikTok, Threads y YouTube entran directamente a Apify en paralelo con las búsquedas. Las demás plataformas usan las fuentes nativas. Los nuevos perfiles admisibles pueden ampliar la búsqueda dentro de las cuotas. Un alias sin plataforma se descubre primero.</p>
    <p className="text-xs text-slate-400">Incluye brechas, Google público y enumeración de correo cuando hay datos compatibles; infostealers con la autorización específica. Los nuevos identificadores alimentan rondas adicionales.</p>
    <p className="text-xs text-slate-400">Presupuesto global de búsqueda: {Math.ceil(plan.deadline_seconds / 60)} minutos. Las fuentes sin respuesta se indican como cobertura parcial.</p>
    {plan.apify_status !== "configured_not_live_validated" && <p role="status" className="text-xs text-amber-300">El enriquecimiento Apify no está disponible en el servidor. La búsqueda pública continúa; su cobertura se indicará por separado.</p>}
  </aside>;
}
