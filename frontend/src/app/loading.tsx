/**
 * Estado de carga por defecto del App Router, mostrado mientras se resuelve un
 * Server Component o se carga el bundle de una ruta.
 */
export default function Loading() {
  return (
    <div role="status" className="py-24 text-center">
      <div
        className="w-6 h-6 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mx-auto mb-3"
        aria-hidden="true"
      />
      <p className="text-xs font-mono text-slate-400">Cargando módulo forense...</p>
    </div>
  );
}
