// =====================================================================
// PERSON-MAP // Cliente HTTP del backend OSINT (FastAPI).
// Endpoints definidos en backend/app/api/v1/*.
// =====================================================================

import type {
  AnalysisNoteData,
  AnalysisNotePayload,
  CreateInvestigationPayload,
  GraphResponse,
  HealthStatus,
  InvestigationData,
  InvestigationLogHistory,
  InvestigationTraceResponse,
  InvestigationReviewData,
  ReviewDecisionValue,
  ReviewFinalizeData,
  ReviewedFootprintDataset,
  ExposureReport,
  ReconstructionReport,
  MetricsComparison,
  SurveyPayload,
  SurveyRead,
  SurveyStats,
  MaigretCapabilities,
  MaigretReportFormat,
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
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
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

function parseErrorCode(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object" || !("code" in detail)) return undefined;
  return String((detail as { code: unknown }).code);
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
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
    throw new ApiError(
      parseErrorDetail(body, `Error ${res.status}: ${res.statusText}`),
      res.status,
      parseErrorCode(body)
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

export function getInvestigationReview(id: string): Promise<InvestigationReviewData> {
  return request<InvestigationReviewData>(`/investigations/${id}/review`);
}

export function decideReviewCandidate(
  investigationId: string,
  candidateId: string,
  decision: ReviewDecisionValue,
): Promise<InvestigationReviewData> {
  return request<InvestigationReviewData>(`/investigations/${investigationId}/review/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify({ decision }),
  });
}

export function finalizeInvestigationReview(id: string): Promise<ReviewFinalizeData> {
  return request<ReviewFinalizeData>(`/investigations/${id}/review/finalize`, { method: "POST" });
}

export function getReviewedFootprint(id: string): Promise<ReviewedFootprintDataset> {
  return request<ReviewedFootprintDataset>(`/investigations/${id}/reviewed-footprint`);
}

export function analyzeExposure(id: string): Promise<ExposureReport> {
  return request<ExposureReport>("/investigations/" + id + "/exposure/analyze", { method: "POST" });
}

export function getExposureReport(id: string): Promise<ExposureReport> {
  return request<ExposureReport>("/investigations/" + id + "/exposure");
}

export function addAnalysisNote(id: string, note: AnalysisNotePayload): Promise<AnalysisNoteData> {
  return request<AnalysisNoteData>(`/investigations/${id}/notes`, { method: "POST", body: JSON.stringify(note) });
}

export function getWorkspaceEventsUrl(): string {
  return `${API_BASE}/workspace/events`;
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

export function getMaigretCapabilities(): Promise<MaigretCapabilities> {
  return request<MaigretCapabilities>("/maigret/capabilities");
}

export async function downloadMaigretReport(id: string, format: MaigretReportFormat): Promise<Blob> {
  const response = await fetch(`${API_BASE}/investigations/${id}/maigret/report?format=${format}`);
  if (!response.ok) {
    let body: unknown = null;
    try { body = await response.json(); } catch { /* Non-JSON upstream failure */ }
    throw new Error(parseErrorDetail(body, `No se pudo exportar el informe (${response.status})`));
  }
  return response.blob();
}

// ---------------------------------------------------------------------
// Consola en vivo (logs + stream SSE)
// ---------------------------------------------------------------------

export function getInvestigationLogs(id: string): Promise<InvestigationLogHistory> {
  return request<InvestigationLogHistory>(`/investigations/${id}/logs`);
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

export function getReconstruction(id: string): Promise<ReconstructionReport> {
  return request<ReconstructionReport>("/investigations/" + id + "/reconstruction");
}

export function buildReconstruction(id: string): Promise<ReconstructionReport> {
  return request<ReconstructionReport>("/investigations/" + id + "/reconstruction/build", { method: "POST" });
}

export function getReconstructionProviders(id: string): Promise<import("./types").ReconstructionProviders> {
  return request("/investigations/" + id + "/reconstruction/providers");
}
export function getMcpReconstruction(id: string): Promise<import("./types").ReconstructionRequest | null> {
  return request("/investigations/" + id + "/reconstruction/mcp");
}
export function requestMcpReconstruction(id: string): Promise<import("./types").ReconstructionRequest> {
  return request("/investigations/" + id + "/reconstruction/mcp", { method: "POST" });
}
export function cancelMcpReconstruction(id: string, requestId: string): Promise<import("./types").ReconstructionRequest> {
  return request("/investigations/" + id + "/reconstruction/mcp/" + requestId + "/cancel", { method: "POST" });
}
