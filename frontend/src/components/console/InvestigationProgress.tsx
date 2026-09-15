"use client";

import { useEffect, useState } from "react";
import { Loader2, Terminal } from "lucide-react";
import { ScanProgressBar } from "@/components/console/LiveConsole";
import {
  findLatestProgress,
  summarizeTools,
  type InvestigationStream,
} from "@/lib/useInvestigationStream";

/**
 * Progreso de la búsqueda, visible en cualquier pestaña mientras dura.
 *
 * La barra existía, pero dentro de la consola: la página abre en el mapa y
 * durante los minutos que tarda la búsqueda no había nada que indicara que el
 * motor seguía trabajando.
 *
 * La barra general es indeterminada a propósito. Ni el agente ni el motor de
 * reglas saben cuántas herramientas lanzarán (depende de lo que vayan
 * encontrando), así que un porcentaje global sería inventado. Lo que sí se
 * sabe se muestra con cifras: herramientas terminadas y, durante el barrido de
 * plataformas, cuántas lleva comprobadas.
 */
export function InvestigationProgress({
  stream,
  startedAt,
  onOpenConsole,
}: {
  stream: InvestigationStream;
  startedAt: string;
  onOpenConsole: () => void;
}) {
  const now = useNow();
  const tools = summarizeTools(stream.logs);
  const scan = findLatestProgress(stream.logs);
  const scanning = scan !== null && scan.checked < scan.total;

  const lastActivity = [...stream.logs]
    .reverse()
    .find((log) => log.phase !== "progress")?.message;

  const started = Date.parse(startedAt);
  const elapsed = now && Number.isFinite(started) ? formatElapsed(now - started) : null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="panel-card px-5 py-4 border border-sky-500/25 print:hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-mono">
          <Loader2 className="w-4 h-4 text-sky-400 animate-spin" aria-hidden="true" />
          <span className="font-bold text-slate-100">Búsqueda en curso</span>
          {elapsed && <span className="text-slate-500 tabular-nums">{elapsed}</span>}
        </div>

        <div className="flex items-center gap-3 text-[11px] font-mono text-slate-400">
          {tools.started > 0 && (
            <span className="tabular-nums">
              {tools.finished} de {tools.started} herramientas terminadas
            </span>
          )}
          <button
            type="button"
            onClick={onOpenConsole}
            className="flex items-center gap-1.5 px-2 py-1 rounded bg-[#182334] hover:bg-[#223148] text-slate-200 border border-[#2b3a52] transition-colors cursor-pointer"
          >
            <Terminal className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
            Ver consola
          </button>
        </div>
      </div>

      <div className="mt-3">
        {scanning ? (
          <div className="rounded-md overflow-hidden border border-[#1b2537]">
            <ScanProgressBar progress={scan} />
          </div>
        ) : (
          <div
            role="progressbar"
            aria-label="Búsqueda en curso"
            className="h-1.5 rounded-full bg-[#161f2e] overflow-hidden"
          >
            <div className="progress-indeterminate h-full w-1/3 rounded-full bg-sky-400" />
          </div>
        )}
      </div>

      {lastActivity && (
        <p className="mt-2 text-[11px] font-mono text-slate-400 truncate" title={lastActivity}>
          {lastActivity}
        </p>
      )}
    </div>
  );
}

/** Hora actual, refrescada cada segundo; `null` hasta el primer tic. */
function useNow(): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const interval = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(interval);
    };
  }, []);
  return now;
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}
