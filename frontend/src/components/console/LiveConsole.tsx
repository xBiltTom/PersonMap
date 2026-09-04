"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Terminal, Check, Loader2, Play, RotateCw, WifiOff } from "lucide-react";
import { getInvestigationLogs, getInvestigationStreamUrl } from "@/lib/api";
import type { StreamLog } from "@/lib/types";

type ConnectionStatus = "connecting" | "live" | "reconnecting" | "closed";

/**
 * Reintentos consecutivos de EventSource antes de rendirse y ofrecer reconexión
 * manual. EventSource reintenta solo cada ~3 s; sin un tope, un backend caído
 * genera peticiones indefinidamente en segundo plano.
 */
const MAX_RECONNECT_ATTEMPTS = 8;

/** Margen en píxeles para considerar que el usuario está "al final" del log. */
const AUTOSCROLL_THRESHOLD_PX = 60;

export function LiveConsole({
  investigationId,
  isFinished,
}: {
  investigationId: string;
  isFinished: boolean;
}) {
  const [logs, setLogs] = useState<StreamLog[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [reconnectKey, setReconnectKey] = useState(0);

  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottomRef = useRef(true);
  const retriesRef = useRef(0);

  // 1. Historial de eventos ya emitidos (replay tras recargar la página)
  const loadLogHistory = useCallback(async () => {
    try {
      const data = await getInvestigationLogs(investigationId);
      if (Array.isArray(data) && data.length > 0) {
        setLogs(data);
      }
      setHistoryError(null);
    } catch (err) {
      setHistoryError(
        err instanceof Error ? err.message : "No se pudo recuperar el registro de eventos"
      );
    } finally {
      setLoadingHistory(false);
    }
  }, [investigationId]);

  useEffect(() => {
    loadLogHistory();
  }, [loadLogHistory]);

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

  // 3. Autoscroll solo si el usuario ya estaba al final; si ha subido a leer
  //    historial no se le arrastra la vista.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    pinnedToBottomRef.current = distanceFromBottom <= AUTOSCROLL_THRESHOLD_PX;
  }, []);

  useEffect(() => {
    if (pinnedToBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const handleManualReconnect = () => {
    retriesRef.current = 0;
    setStatus("connecting");
    loadLogHistory();
    setReconnectKey((k) => k + 1);
  };

  return (
    <div className="panel-card overflow-hidden flex flex-col h-[420px] sm:h-[540px] bg-[#070b12] border border-[#1b2537]">
      {/* Cabecera */}
      <div className="px-4 py-2.5 bg-[#0e1420] border-b border-[#1b2537] flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
          <span className="text-xs font-mono font-bold text-slate-300">
            STREAM // ORCHESTRATION EVENT LOG
          </span>
        </div>

        <div className="flex items-center gap-3 text-[11px] font-mono">
          <span className="text-slate-400">{logs.length} eventos registrados</span>
          <ConnectionBadge
            status={status}
            isFinished={isFinished}
            onReconnect={handleManualReconnect}
          />
        </div>
      </div>

      {/* Cuerpo del terminal */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        aria-label="Registro de eventos de la investigación en vivo"
        className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1.5 selection:bg-sky-500 selection:text-white"
      >
        {historyError && (
          <div className="mb-2 px-2 py-1.5 rounded bg-rose-950/30 border border-rose-500/30 text-rose-300 flex items-center gap-2">
            <WifiOff className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            <span>{historyError}</span>
          </div>
        )}

        {loadingHistory && logs.length === 0 ? (
          <div className="text-slate-400 italic flex items-center gap-2 py-4">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" aria-hidden="true" />
            Recuperando registro de eventos...
          </div>
        ) : logs.length === 0 ? (
          <div className="text-slate-400 italic flex items-center gap-2 py-4">
            <Play className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
            Esperando inicio de la ejecución del motor...
          </div>
        ) : (
          logs.map((log, i) => <LogLine key={`${log.timestamp}-${i}`} log={log} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function ConnectionBadge({
  status,
  isFinished,
  onReconnect,
}: {
  status: ConnectionStatus;
  isFinished: boolean;
  onReconnect: () => void;
}) {
  if (status === "live") {
    return (
      <span className="flex items-center gap-1.5 text-emerald-400 font-semibold">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" aria-hidden="true" />
        En Vivo
      </span>
    );
  }

  if (status === "reconnecting") {
    return (
      <span className="flex items-center gap-1.5 text-amber-300 font-semibold">
        <RotateCw className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
        Reconectando...
      </span>
    );
  }

  if (status === "connecting") {
    return (
      <span className="flex items-center gap-1.5 text-slate-300">
        <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
        Conectando...
      </span>
    );
  }

  // status === "closed"
  if (isFinished) {
    return (
      <span className="flex items-center gap-1 text-emerald-400">
        <Check className="w-3.5 h-3.5" aria-hidden="true" /> Finalizado
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onReconnect}
      className="flex items-center gap-1.5 px-2 py-0.5 rounded text-rose-300 bg-rose-950/30 border border-rose-500/30 hover:bg-rose-900/40 transition-colors cursor-pointer"
    >
      <WifiOff className="w-3.5 h-3.5" aria-hidden="true" />
      Sin conexión — Reconectar
    </button>
  );
}

/**
 * Estilo de cada línea según su naturaleza.
 *
 * Antes la clasificación solo miraba `log.type`. Como los eventos del agente IA
 * viajan con `type: "log"` y la etapa en `phase`, un `agent_error` -- que es un
 * fallo real -- se pintaba en gris neutro, indistinguible de una línea normal.
 * Aquí se consulta `phase` además de `type`.
 */
function logLineStyle(log: StreamLog): string {
  const { type, phase } = log;

  if (type === "investigation_error" || type === "tool_error" || phase === "agent_error") {
    return "text-rose-400 bg-rose-950/20 px-1 py-0.5 rounded";
  }
  if (type === "investigation_complete" || phase === "complete") {
    return "text-emerald-300 font-semibold bg-emerald-950/20 px-1 py-0.5 rounded";
  }
  if (phase === "pivot") {
    return "text-amber-300";
  }
  if (phase === "agent_reasoning") {
    return "text-purple-300 italic";
  }
  if (phase === "agent_start" || phase === "agent_tool_dispatch" || phase === "agent_concluded") {
    return "text-purple-300";
  }
  if (phase === "init" || phase?.startsWith("round_")) {
    return "text-slate-100 font-semibold";
  }
  if (phase === "progress") {
    return "text-slate-400";
  }
  if (type === "tool_start" || type === "tool_complete") {
    return "text-sky-300";
  }
  return "text-slate-300";
}

function LogLine({ log }: { log: StreamLog }) {
  const timeStr = log.timestamp
    ? new Date(log.timestamp * 1000).toLocaleTimeString("es-ES", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "--:--:--";

  return (
    <div className={`flex items-start gap-2.5 leading-relaxed font-mono ${logLineStyle(log)}`}>
      <span className="text-slate-500 shrink-0 select-none">[{timeStr}]</span>
      {log.tool && (
        <span className="text-sky-400 shrink-0 font-bold select-none">
          [{log.tool.toUpperCase()}]
        </span>
      )}
      <span className="break-words min-w-0">{log.message}</span>
    </div>
  );
}
