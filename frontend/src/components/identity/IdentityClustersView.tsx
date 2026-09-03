"use client";

import { useState } from "react";
import { IdentityClusterData, EntityData } from "@/lib/types";
import { verifyEntity } from "@/lib/api";
import {
  CheckCircle,
  AlertCircle,
  XCircle,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  HelpCircle,
} from "lucide-react";

interface Props {
  investigationId: string;
  clusters: IdentityClusterData[];
  onEntityUpdated?: () => void;
}

export function IdentityClustersView({ investigationId, clusters, onEntityUpdated }: Props) {
  const [loadingEntityId, setLoadingEntityId] = useState<string | null>(null);

  const handleVerify = async (entityId: string, verified: boolean) => {
    try {
      setLoadingEntityId(entityId);
      await verifyEntity(investigationId, entityId, verified);
      if (onEntityUpdated) onEntityUpdated();
    } catch (err) {
      console.error("Error al verificar entidad", err);
    } finally {
      setLoadingEntityId(null);
    }
  };

  if (!clusters || clusters.length === 0) {
    return (
      <div className="panel-card p-8 text-center text-slate-500 font-mono text-xs">
        No se han generado clusters de identidad para este objetivo aún.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between pb-3 border-b border-[#1e293b]">
        <div>
          <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-sky-400" />
            Reconstrucción de Identidad y Desanonimización
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Agrupación de hallazgos que comparten correlación verificada vs homónimos descartados.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6">
        {clusters.map((cluster) => {
          const isHigh = cluster.confidence >= 0.70;
          const isProbable = cluster.confidence >= 0.40 && cluster.confidence < 0.70;

          return (
            <div
              key={cluster.id}
              className={`panel-card p-5 border ${
                isHigh
                  ? "border-emerald-500/30 bg-[#0f171d]"
                  : isProbable
                  ? "border-amber-500/30 bg-[#14181f]"
                  : "border-slate-800 bg-[#0f131a] opacity-80"
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  {isHigh ? (
                    <CheckCircle className="w-5 h-5 text-emerald-400" />
                  ) : isProbable ? (
                    <AlertCircle className="w-5 h-5 text-amber-400" />
                  ) : (
                    <XCircle className="w-5 h-5 text-slate-500" />
                  )}
                  <div>
                    <h4 className="text-sm font-semibold text-slate-200">{cluster.label}</h4>
                    <p className="text-[11px] text-slate-400 mt-0.5">{cluster.reasoning}</p>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <span
                    className={`text-base font-mono font-bold ${
                      isHigh ? "text-emerald-400" : isProbable ? "text-amber-400" : "text-slate-500"
                    }`}
                  >
                    {Math.round(cluster.confidence * 100)}%
                  </span>
                  <span className="text-[10px] font-mono text-slate-500 block uppercase">
                    Certeza
                  </span>
                </div>
              </div>

              {/* Entities list within this cluster */}
              {cluster.entities && cluster.entities.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[#1e293b] space-y-2">
                  <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider block mb-2">
                    Entidades vinculadas en este grupo ({cluster.entities.length}):
                  </span>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                    {cluster.entities.map((entity) => (
                      <div
                        key={entity.id}
                        className="p-3 rounded-md bg-[#131b28] border border-[#1e293b] flex items-center justify-between text-xs"
                      >
                        <div className="min-w-0 pr-3">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[10px] font-mono uppercase text-sky-400 font-semibold">
                              {entity.platform || entity.entity_type}
                            </span>
                            <span className="text-slate-500">•</span>
                            <span className="text-[10px] font-mono text-slate-400">
                              {Math.round(entity.confidence * 100)}%
                            </span>
                            {entity.verified && (
                              <span className="text-[9px] font-mono px-1 rounded bg-emerald-500/20 text-emerald-400">
                                Verificado
                              </span>
                            )}
                          </div>

                          <div className="font-semibold text-slate-200 truncate mt-0.5">
                            {entity.display_name || entity.value}
                          </div>

                          {entity.value.startsWith("http") && (
                            <a
                              href={entity.value}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[11px] text-sky-400/80 hover:underline flex items-center gap-1 mt-0.5 truncate"
                            >
                              <span className="truncate">{entity.value}</span>
                              <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                            </a>
                          )}
                        </div>

                        {/* Manual Verification Actions */}
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => handleVerify(entity.id, true)}
                            disabled={loadingEntityId === entity.id || entity.verified}
                            title="Confirmar que pertenece a la persona"
                            className="px-2 py-1 rounded text-[10px] font-mono bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 disabled:opacity-40 transition-colors"
                          >
                            ✓ Confirmar
                          </button>
                          <button
                            onClick={() => handleVerify(entity.id, false)}
                            disabled={loadingEntityId === entity.id || !entity.verified}
                            title="Descartar como homónimo"
                            className="px-2 py-1 rounded text-[10px] font-mono bg-slate-800 hover:bg-slate-700 text-slate-400 border border-slate-700 disabled:opacity-40 transition-colors"
                          >
                            ✕ Descartar
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
