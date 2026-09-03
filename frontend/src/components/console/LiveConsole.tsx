"use client";

import { useEffect, useState, useRef } from "react";
import { Terminal, Check, Loader2, ArrowDownCircle } from "lucide-react";

interface StreamLog {
  type: string;
  message: string;
  timestamp: number;
  tool?: string;
  phase?: string;
}

export function LiveConsole({
  investigationId,
  isFinished,
}: {
  investigationId: string;
  isFinished: boolean;
}) {
  const [logs, setLogs] = useState<StreamLog[]>([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const url = `http://localhost:8000/api/v1/investigations/${investigationId}/stream`;
    const eventSource = new EventSource(url);

    eventSource.onopen = () => {
      setConnected(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.message) {
          setLogs((prev) => [...prev, data]);
        }
        if (data.type === "investigation_complete" || data.type === "investigation_error") {
          eventSource.close();
        }
      } catch (err) {
        // Ping or non-json message
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setConnected(false);
    };

    return () => {
      eventSource.close();
    };
  }, [investigationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="panel-card overflow-hidden flex flex-col h-[520px] bg-[#070b12] border border-[#1b2537]">
      {/* Console Header */}
      <div className="px-4 py-2.5 bg-[#0e1420] border-b border-[#1b2537] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-sky-400" />
          <span className="text-xs font-mono font-bold text-slate-300">
            STREAM // ORCHESTRATION EVENT LOG
          </span>
        </div>

        <div className="flex items-center gap-2 text-[11px] font-mono">
          {connected ? (
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              En Vivo
            </span>
          ) : isFinished ? (
            <span className="flex items-center gap-1 text-slate-400">
              <Check className="w-3 h-3 text-emerald-400" /> Finalizado
            </span>
          ) : (
            <span className="text-slate-500">Desconectado</span>
          )}
        </div>
      </div>

      {/* Terminal Body */}
      <div className="flex-1 p-4 overflow-y-auto font-mono text-xs space-y-1.5 selection:bg-sky-500 selection:text-white">
        {logs.length === 0 ? (
          <div className="text-slate-500 italic flex items-center gap-2 py-4">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
            Esperando despacho del motor de investigación...
          </div>
        ) : (
          logs.map((log, i) => {
            const timeStr = new Date(log.timestamp * 1000).toLocaleTimeString("es-ES", {
              hour12: false,
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });

            const isComplete = log.type === "investigation_complete";
            const isError = log.type === "investigation_error" || log.type === "tool_error";
            const isPivot = log.phase === "pivot";

            return (
              <div
                key={i}
                className={`flex items-start gap-2.5 leading-relaxed ${
                  isComplete
                    ? "text-emerald-300 font-semibold"
                    : isError
                    ? "text-rose-400"
                    : isPivot
                    ? "text-amber-300"
                    : "text-slate-300"
                }`}
              >
                <span className="text-slate-600 shrink-0 select-none">[{timeStr}]</span>
                {log.tool && (
                  <span className="text-sky-400 shrink-0 select-none">
                    [{log.tool.toUpperCase()}]
                  </span>
                )}
                <span>{log.message}</span>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
