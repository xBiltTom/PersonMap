"use client";

import { useState } from "react";
import type { ReconstructionProviders, ReconstructionRequest } from "../../lib/types";

export type ReconstructionMode = "integrated" | "mcp";
export function mcpRequestActive(request: ReconstructionRequest | null) {
  return !!request && !request.stale && (request.status === "pending" || request.status === "running");
}

export function ReconstructionProviderChoice({ mode, providers, disabled, onChange }: {
  mode: ReconstructionMode; providers: ReconstructionProviders | null; disabled: boolean;
  onChange: (mode: ReconstructionMode) => void;
}) {
  return <fieldset className="reconstruction-provider-choice" disabled={disabled}>
    <legend>Elige cómo analizar la huella</legend>
    <label data-selected={mode === "integrated"}>
      <input type="radio" name="reconstruction-provider" value="integrated" checked={mode === "integrated"}
        onChange={() => onChange("integrated")} />
      <span><strong>{providers?.integrated.label || "Google AI Studio"}</strong>
        <small>La IA configurada en PersonMap analiza el texto desde el backend.</small></span>
    </label>
    <label data-selected={mode === "mcp"}>
      <input type="radio" name="reconstruction-provider" value="mcp" checked={mode === "mcp"}
        onChange={() => onChange("mcp")} />
      <span><strong>Codex por MCP</strong><small>Codex analiza textos e imágenes y envía el resultado a esta vista.</small></span>
    </label>
  </fieldset>;
}

export function McpReconstructionPanel({ request, enabled, reason, busy, error, onRequest, onCancel }: {
  request: ReconstructionRequest | null; enabled: boolean; reason?: string | null;
  busy: boolean; error: { message: string } | null; onRequest: () => void; onCancel: () => void;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const active = mcpRequestActive(request);
  async function copy(text: string, label: string) {
    try { await navigator.clipboard.writeText(text); setCopyStatus(`${label} copiado.`); }
    catch { setCopyStatus("No se pudo copiar. Selecciona el texto y cópialo manualmente."); }
  }
  const labels = { pending: "Esperando a Codex", running: "Codex está analizando", completed: "Resultado recibido",
    failed: "El análisis no se completó", cancelled: "Solicitud cancelada" };
  return <section className="reconstruction-panel" aria-label="Análisis desde Codex">
    <h2>Reconstrucción con Codex por MCP</h2>
    <p>Crea la solicitud, abre Codex con el comando y mantén esta vista abierta. El resultado aparecerá cuando el agente lo envíe.</p>
    {!enabled && <p role="status">{reason || "El MCP del backend no está disponible."}</p>}
    {error && <p role="alert">{error.message}</p>}
    {request && <div className="reconstruction-mcp-status" role="status" aria-live="polite">
      <strong>{request.stale ? "La evidencia cambió: crea una solicitud nueva" : labels[request.status]}</strong>
      {!request.stale && <p>{request.progress.message}</p>}
      {request.status === "running" && !request.stale && <p>
        {request.progress.analyzed_posts || 0} de {request.progress.total_posts || 0} publicaciones informadas por el agente
      </p>}
      {request.client && <small>{request.client}{request.model ? ` · ${request.model}` : ""}</small>}
    </div>}
    {active && request && <>
      <h3>1. Abre una terminal en la raíz de PersonMap</h3>
      <pre className="reconstruction-command"><code>{request.command}</code></pre>
      <button type="button" onClick={() => void copy(request.command, "Comando")}>Copiar comando</button>
      <p>Este comando abre Codex con la conexión MCP y el encargo de esta solicitud. La credencial se lee del entorno local.</p>
      <details className="reconstruction-claim">
        <summary>Ya tengo Codex conectado: copiar el encargo</summary>
        <textarea aria-label="Encargo para Codex" readOnly value={request.prompt} rows={6} />
        <button type="button" onClick={() => void copy(request.prompt, "Encargo")}>Copiar encargo</button>
      </details>
      <p>2. Codex debe enviar el resultado con <code>submit_reconstruction_result</code>. Una respuesta en el chat no completa la solicitud.</p>
      <button type="button" onClick={onCancel} disabled={busy}>Cancelar espera</button>
    </>}
    <p role="status">{copyStatus}</p>
    {!active && <button type="button" onClick={onRequest} disabled={busy || !enabled}>
      {busy ? "Preparando solicitud…" : request ? "Solicitar otro análisis en Codex" : "Solicitar análisis en Codex"}
    </button>}
  </section>;
}
