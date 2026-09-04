// =====================================================================
// PERSON-MAP // Cliente HTTP del backend OSINT (FastAPI).
// Endpoints definidos en backend/app/api/v1/*.
// =====================================================================

import type {
  CreateInvestigationPayload,
  GraphResponse,
  InvestigationData,
} from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8000/api/v1";

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

export function deleteInvestigation(id: string): Promise<void> {
  return request<void>(`/investigations/${id}`, { method: "DELETE" });
}

export function verifyEntity(
  investigationId: string,
  entityId: string,
  verified: boolean,
  verificationNotes?: string
): Promise<void> {
  return request<void>(
    `/investigations/${investigationId}/verify-entity/${entityId}`,
    {
      method: "POST",
      body: JSON.stringify({
        verified,
        verification_notes: verificationNotes ?? null,
      }),
    }
  );
}

// ---------------------------------------------------------------------
// Grafo / mapa digital
// ---------------------------------------------------------------------

export function getInvestigationGraph(id: string): Promise<GraphResponse> {
  return request<GraphResponse>(`/investigations/${id}/graph`);
}
