// =====================================================================
// PERSON-MAP // Cliente HTTP del backend OSINT (FastAPI).
// Endpoints definidos en backend/app/api/v1/*.
// =====================================================================

import type {
  CreateInvestigationPayload,
  GraphResponse,
  HealthStatus,
  InvestigationData,
  InvestigationTraceResponse,
  MetricsComparison,
  StreamLog,
  SurveyPayload,
  SurveyRead,
  SurveyStats,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8000/api/v1";

/**
 * Origen del backend, sin el prefijo /api/v1. Necesario para los endpoints que
 * viven fuera de la API versionada (`/health`) y para construir URLs que no
 * consume `fetch` sino el navegador (EventSource del stream SSE, descarga
 * directa del GraphML).
 */
export const API_ORIGIN = API_BASE.replace(/\/api\/v1$/, "");

/** Extrae un mensaje legible del cuerpo de error de FastAPI. */
function parseErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) =>
        d && typeof d === "object" && "msg" in d
          ? String((d as { msg: unknown }).msg)
          : String(d)
      )
      .filter(Boolean);
    if (msgs.length) return msgs.join(" · ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      ...init,
    });
  } catch {
    throw new Error(
      "No se pudo contactar el backend OSINT. ¿Está corriendo en el puerto 8000?"
    );
  }

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    throw new Error(
      parseErrorDetail(body, `Error ${res.status}: ${res.statusText}`)
    );
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------
// Investigaciones
// ---------------------------------------------------------------------

export function createInvestigation(
  payload: CreateInvestigationPayload
): Promise<InvestigationData> {
  return request<InvestigationData>("/investigations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listInvestigations(
  limit = 50,
  offset = 0
): Promise<InvestigationData[]> {
  return request<InvestigationData[]>(
    `/investigations?limit=${limit}&offset=${offset}`
  );
}

export function getInvestigation(id: string): Promise<InvestigationData> {
  return request<InvestigationData>(`/investigations/${id}`);
}

export function getInvestigationTrace(id: string): Promise<InvestigationTraceResponse> {
  return request<InvestigationTraceResponse>(`/investigations/${id}/trace`);
}

export function deleteInvestigation(id: string): Promise<void> {
  return request<void>(`/investigations/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------
// Grafo / mapa digital
// ---------------------------------------------------------------------

export function getInvestigationGraph(id: string): Promise<GraphResponse> {
  return request<GraphResponse>(`/investigations/${id}/graph`);
}

/** URL de descarga del GraphML para Gephi/Cytoscape (la abre el navegador). */
export function getGraphmlUrl(id: string): string {
  return `${API_BASE}/investigations/${id}/graphml`;
}

// ---------------------------------------------------------------------
// Consola en vivo (logs + stream SSE)
// ---------------------------------------------------------------------

export function getInvestigationLogs(id: string): Promise<StreamLog[]> {
  return request<StreamLog[]>(`/investigations/${id}/logs`);
}

/** URL del stream SSE. La consume `EventSource`, no `fetch`. */
export function getInvestigationStreamUrl(id: string): string {
  return `${API_BASE}/investigations/${id}/stream`;
}

// ---------------------------------------------------------------------
// Métricas y salud
// ---------------------------------------------------------------------

export function getMetricsComparison(): Promise<MetricsComparison> {
  return request<MetricsComparison>("/investigations/metrics/comparison");
}

/**
 * Comprueba si el backend responde. Vive fuera de `/api/v1`, de ahí que use
 * `API_ORIGIN` en lugar del helper `request`.
 */
export async function checkHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_ORIGIN}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend respondió ${res.status}`);
  return (await res.json()) as HealthStatus;
}

// ---------------------------------------------------------------------
// Encuesta de concientización
// ---------------------------------------------------------------------

export function createSurvey(payload: SurveyPayload): Promise<SurveyRead> {
  return request<SurveyRead>("/surveys", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSurveyStats(): Promise<SurveyStats> {
  return request<SurveyStats>("/surveys/stats");
}
