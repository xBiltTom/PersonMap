"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCw, ArrowLeft } from "lucide-react";

/**
 * Error Boundary de ruta del App Router.
 *
 * Sin este fichero, cualquier excepción durante el render de un Client Component
 * (por ejemplo un campo inesperado en la respuesta del backend) escalaba a la
 * pantalla de error genérica de Next, que en producción no dice nada útil ni
 * ofrece salida.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[PersonMap] Error de ruta:", error);
  }, [error]);

  return (
    <div className="panel-card p-8 text-center max-w-lg mx-auto my-16 border border-rose-500/30">
      <AlertTriangle className="w-10 h-10 text-rose-400 mx-auto mb-3" aria-hidden="true" />
      <h2 className="text-base font-semibold text-slate-100">
        Se produjo un error inesperado
      </h2>
      <p className="text-xs text-slate-400 mt-2 max-w-md mx-auto break-words">
        {error.message || "La interfaz no pudo renderizar esta sección."}
      </p>
      {error.digest && (
        <p className="text-[11px] font-mono text-slate-500 mt-2">
          Referencia: {error.digest}
        </p>
      )}

      <div className="mt-5 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-xs font-mono font-semibold transition-colors cursor-pointer"
        >
          <RotateCw className="w-3.5 h-3.5" aria-hidden="true" />
          Reintentar
        </button>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 text-xs font-mono border border-[#2b3a52] transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" />
          Volver al panel
        </Link>
      </div>
    </div>
  );
}
