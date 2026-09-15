"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getInvestigationLogs, getInvestigationStreamUrl } from "@/lib/api";
import type { StreamLog } from "@/lib/types";

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "closed";

/**
 * Reintentos consecutivos de EventSource antes de rendirse y ofrecer reconexión
 * manual. EventSource reintenta solo cada ~3 s; sin un tope, un backend caído
 * genera peticiones indefinidamente en segundo plano.
 */
const MAX_RECONNECT_ATTEMPTS = 8;

export interface InvestigationStream {
  logs: StreamLog[];
  status: ConnectionStatus;
  loadingHistory: boolean;
  historyError: string | null;
  reconnect: () => void;
}

/**
 * Historial y eventos en vivo de una investigación.
 *
 * Vivía dentro de `LiveConsole`, así que solo había stream mientras la pestaña
 * de consola estaba abierta. La página arranca en el mapa, de modo que durante
 * toda la búsqueda nada escuchaba el progreso. Ahora lo abre la página una sola
 * vez y lo comparten la consola y la barra de progreso de la cabecera.
 *
 * `onFinished` se llama al recibir el cierre de la investigación, para que la
 * página no espere al siguiente sondeo para mostrar el resultado.
 */
export function useInvestigationStream(
  investigationId: string,
  onFinished?: () => void
): InvestigationStream {
  const [logs, setLogs] = useState<StreamLog[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reconnectKey, setReconnectKey] = useState(0);

  const retriesRef = useRef(0);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  });

  // 1. Historial de eventos ya emitidos (replay tras recargar la página). Se
  //    vuelve a pedir en cada reconexión manual; si el componente se desmonta o
  //    se reconecta antes de que responda, esa respuesta ya no se aplica.
  useEffect(() => {
    let cancelled = false;
    getInvestigationLogs(investigationId)
      .then((data) => {
        if (cancelled) return;
        if (Array.isArray(data) && data.length > 0) {
          setLogs(data);
        }
        setHistoryError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setHistoryError(
          err instanceof Error ? err.message : "No se pudo recuperar el registro de eventos"
        );
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, [investigationId, reconnectKey]);

  // 2. Stream SSE en tiempo real
  useEffect(() => {
    const eventSource = new EventSource(getInvestigationStreamUrl(investigationId));

    eventSource.onopen = () => {
      retriesRef.current = 0;
      setStatus("live");
    };

    eventSource.onmessage = (event) => {
      try {
        const data: StreamLog = JSON.parse(event.data);
        if (data.message) {
          setLogs((prev) => {
            // El backend reproduce el historial al suscribirse, así que tras una
            // reconexión llegan de nuevo eventos ya pintados. Se descartan por
            // (mensaje, timestamp) exactos; antes se usaba una ventana de 1 s que
            // además tragaba eventos legítimamente repetidos dentro del segundo.
            const exists = prev.some(
              (p) => p.message === data.message && p.timestamp === data.timestamp
            );
            return exists ? prev : [...prev, data];
          });
        }
        if (data.type === "investigation_complete" || data.type === "investigation_error") {
          eventSource.close();
          setStatus("closed");
          onFinishedRef.current?.();
        }
      } catch {
        // Comentario keep-alive o carga no JSON: se ignora.
      }
    };

    eventSource.onerror = () => {
      // No se llama a close() aquí. EventSource reintenta la conexión por su
      // cuenta, y cerrarlo en onerror -- como se hacía antes -- cancelaba ese
      // reintento nativo y dejaba la consola muerta tras el primer hipo de red.
      if (eventSource.readyState === EventSource.CLOSED) {
        setStatus("closed");
        return;
      }

      retriesRef.current += 1;
      if (retriesRef.current >= MAX_RECONNECT_ATTEMPTS) {
        eventSource.close();
        setStatus("closed");
      } else {
        setStatus("reconnecting");
      }
    };

    return () => {
      eventSource.close();
    };
  }, [investigationId, reconnectKey]);

  const reconnect = useCallback(() => {
    retriesRef.current = 0;
    setStatus("connecting");
    setReconnectKey((k) => k + 1);
  }, []);

  return { logs, status, loadingHistory, historyError, reconnect };
}

export interface ScanProgress {
  tool: string;
  checked: number;
  total: number;
  pct: number;
  subject?: string;
}

/**
 * Último evento de progreso que traiga cifras.
 *
 * Se recorre de atrás hacia delante porque solo interesa el más reciente, y los
 * eventos antiguos siguen en el historial tras una reconexión.
 */
export function findLatestProgress(logs: StreamLog[]): ScanProgress | null {
  for (let i = logs.length - 1; i >= 0; i--) {
    const log = logs[i];
    if (
      log.phase === "progress" &&
      typeof log.checked === "number" &&
      typeof log.total === "number" &&
      log.total > 0
    ) {
      return {
        tool: log.tool || "escaneo",
        checked: log.checked,
        total: log.total,
        pct: typeof log.pct === "number" ? log.pct : (log.checked / log.total) * 100,
        subject: log.subject,
      };
    }
  }
  return null;
}

/**
 * Herramientas lanzadas y terminadas, sea cual sea el motor.
 *
 * Cada motor anuncia el lanzamiento a su manera (`tool_start` el de reglas,
 * `agent_tool_dispatch` el agente, `hybrid_refine_dispatch` la capa de IA del
 * híbrido), pero los tres cierran con `tool_complete` o `tool_error`.
 */
export function summarizeTools(logs: StreamLog[]): { started: number; finished: number } {
  let started = 0;
  let finished = 0;
  for (const log of logs) {
    if (
      log.type === "tool_start" ||
      log.phase === "agent_tool_dispatch" ||
      log.phase === "hybrid_refine_dispatch"
    ) {
      started++;
    } else if (log.type === "tool_complete" || log.type === "tool_error") {
      finished++;
    }
  }
  return { started: Math.max(started, finished), finished };
}
