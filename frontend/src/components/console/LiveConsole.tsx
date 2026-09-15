"use client";

import { useEffect, useRef, useCallback } from "react";
import { Terminal, Check, Loader2, Play, RotateCw, WifiOff } from "lucide-react";
import type { StreamLog } from "@/lib/types";
import {
  findLatestProgress,
  type ConnectionStatus,
  type InvestigationStream,
  type ScanProgress,
} from "@/lib/useInvestigationStream";

/** Margen en píxeles para considerar que el usuario está "al final" del log. */
const AUTOSCROLL_THRESHOLD_PX = 60;

/**
 * Consola de eventos de la investigación.
 *
 * El stream lo abre la página (`useInvestigationStream`) y lo comparte con la
 * barra de progreso de la cabecera; esta vista solo lo pinta.
 */
export function LiveConsole({
  stream,
  isFinished,
}: {
  stream: InvestigationStream;
  isFinished: boolean;
}) {
  const { logs, status, loadingHistory, historyError, reconnect } = stream;

  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottomRef = useRef(true);

  // Autoscroll solo si el usuario ya estaba al final; si ha subido a leer
  // historial no se le arrastra la vista.
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

  // El distintivo de capa solo tiene sentido cuando la investigación tiene DOS:
  // en una corrida puramente heurística marcaría cada línea con la misma
  // etiqueta y sería ruido. Se activa en cuanto aparece una línea de refinamiento.
  const hasTwoLayers = logs.some((l) => l.layer === "refinement");

  // Último evento de progreso con cifras. El backend lo emite cada 25 sitios
  // comprobados; hasta ahora se pintaba como una línea de log más y el usuario
  // veía una consola aparentemente detenida durante minutos.
  const progress = findLatestProgress(logs);

  // Las líneas de progreso salen de la consola en cuanto hay barra: son ~20
  // repeticiones de "Progreso: X/500" que dicen exactamente lo que la barra ya
  // muestra, y sepultan los eventos que sí importan (rondas, pivoteos, capas).
  const visibleLogs = progress ? logs.filter((l) => l.phase !== "progress") : logs;

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
          {hasTwoLayers && (
            <span className="flex items-center gap-2 text-slate-400">
              <span className="flex items-center gap-1">
                <span className="w-4 text-center text-[9px] font-bold px-1 py-px rounded border bg-sky-500/10 text-sky-300 border-sky-500/30">
                  H
                </span>
                <span>Capa 1 · heurística</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-6 text-center text-[9px] font-bold px-1 py-px rounded border bg-purple-500/10 text-purple-300 border-purple-500/30">
                  IA
                </span>
                <span>Capa 2 · refinamiento</span>
              </span>
            </span>
          )}
          <span className="text-slate-400" title="Total de eventos recibidos, incluidos los de progreso que resume la barra">
            {logs.length} eventos registrados
          </span>
          <ConnectionBadge
            status={status}
            isFinished={isFinished}
            onReconnect={reconnect}
          />
        </div>
      </div>

      {!isFinished && progress && <ScanProgressBar progress={progress} />}

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

        {loadingHistory && visibleLogs.length === 0 ? (
          <div className="text-slate-400 italic flex items-center gap-2 py-4">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" aria-hidden="true" />
            Recuperando registro de eventos...
          </div>
        ) : visibleLogs.length === 0 ? (
          <div className="text-slate-400 italic flex items-center gap-2 py-4">
            <Play className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
            Esperando inicio de la ejecución del motor...
          </div>
        ) : (
          visibleLogs.map((log, i) => (
            <LogLine
              key={`${log.timestamp}-${i}`}
              log={log}
              showLayer={hasTwoLayers}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

/**
 * Barra de progreso del escaneo de plataformas.
 *
 * Es la diferencia entre una demo que se sostiene y una que no: el barrido de
 * cientos de sitios tarda minutos, y sin esto la pantalla parece congelada
 * justo cuando hay un jurado mirando.
 */
export function ScanProgressBar({ progress }: { progress: ScanProgress }) {
  const pct = Math.min(100, Math.max(0, progress.pct));

  return (
    <div className="px-4 py-2.5 border-b border-[#1b2537] bg-[#0a0f18]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 mb-1.5 text-[11px] font-mono">
        <span className="text-slate-300">
          <span className="text-sky-400">[{progress.tool.toUpperCase()}]</span>{" "}
          {progress.subject ? (
            <>
              comprobando <span className="text-slate-100">@{progress.subject}</span>
            </>
          ) : (
            "escaneando plataformas"
          )}
        </span>
        <span className="text-slate-400 tabular-nums">
          {progress.checked} / {progress.total} plataformas ·{" "}
          <span className="text-slate-100 font-semibold">{pct.toFixed(0)}%</span>
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Progreso del escaneo de plataformas: ${progress.checked} de ${progress.total}`}
        className="h-1.5 rounded-full bg-[#161f2e] overflow-hidden"
      >
        <div
          className="h-full rounded-full bg-sky-400 transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
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
  if (phase === "hybrid_start" || phase === "hybrid_layer1_complete") {
    return "text-slate-100 font-semibold";
  }
  if (
    phase === "hybrid_degraded" ||
    phase === "hybrid_refine_error" ||
    phase === "hybrid_refine_retry" ||
    phase === "agent_retry" ||
    phase === "agent_fallback"
  ) {
    return "text-amber-300";
  }
  if (phase === "catalog_filter") {
    // Trabajo ahorrado, no trabajo hecho: se distingue de una comprobación real.
    return "text-emerald-300/80";
  }
  if (phase === "hybrid_refine_skipped") {
    // Una llamada que el barrido ya cubrió y el motor ahorró: no es un error,
    // pero conviene que se distinga de una que sí se ejecutó.
    return "text-slate-400 italic";
  }
  if (phase === "hybrid_arbitration_verdict" || phase === "hybrid_arbitration") {
    return "text-fuchsia-300";
  }
  if (phase === "agent_reasoning" || phase === "hybrid_refine_reasoning") {
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

const LAYER_BADGE: Record<string, { text: string; className: string; title: string }> = {
  heuristic: {
    text: "H",
    className: "bg-sky-500/10 text-sky-300 border-sky-500/30",
    title: "Capa 1 · barrido heurístico determinista",
  },
  refinement: {
    text: "IA",
    className: "bg-purple-500/10 text-purple-300 border-purple-500/30",
    title: "Capa 2 · refinamiento por IA sobre los huecos del barrido",
  },
};

function LogLine({ log, showLayer = false }: { log: StreamLog; showLayer?: boolean }) {
  const timeStr = log.timestamp
    ? new Date(log.timestamp * 1000).toLocaleTimeString("es-ES", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "--:--:--";

  const badge = log.layer ? LAYER_BADGE[log.layer] : undefined;

  return (
    <div className={`flex items-start gap-2.5 leading-relaxed font-mono ${logLineStyle(log)}`}>
      <span className="text-slate-500 shrink-0 select-none">[{timeStr}]</span>
      {showLayer && (
        <span
          title={badge?.title}
          className={`shrink-0 select-none w-7 text-center text-[9px] font-bold px-1 py-px rounded border ${
            badge?.className ?? "border-transparent text-transparent"
          }`}
        >
          {badge?.text ?? ""}
        </span>
      )}
      {log.tool && (
        <span className="text-sky-400 shrink-0 font-bold select-none">
          [{log.tool.toUpperCase()}]
        </span>
      )}
      <span className="break-words min-w-0">{log.message}</span>
    </div>
  );
}
