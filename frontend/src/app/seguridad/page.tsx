import Link from "next/link";
import { ArrowLeft, ShieldAlert } from "lucide-react";
import { PasswordExposureCheck } from "@/components/security/PasswordExposureCheck";

export const metadata = {
  title: "Autodefensa · PersonMap",
  description:
    "Comprueba si tu contraseña aparece en filtraciones públicas, sin que salga de tu navegador.",
};

/**
 * Ruta separada de las investigaciones a propósito.
 *
 * El resto del proyecto responde "qué puede averiguar un tercero sobre esta
 * persona". Esta página responde a la pregunta que viene después, y que es la
 * que de verdad justifica una herramienta educativa: "y yo qué hago al
 * respecto". Mezclarla con el expediente confundiría las dos cosas.
 */
export default function SecurityPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Link
          href="/"
          className="text-xs font-mono text-slate-400 hover:text-sky-400 flex items-center gap-1 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" /> Volver al inicio
        </Link>
      </div>

      <section className="max-w-3xl">
        <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 font-mono text-xs mb-4">
          <ShieldAlert className="w-3.5 h-3.5" aria-hidden="true" />
          <span>Autodefensa</span>
        </div>

        <h1 className="text-2xl font-bold tracking-tight text-slate-100">
          Comprueba tu propia exposición
        </h1>

        <p className="mt-3 text-sm text-slate-400 leading-relaxed">
          Una investigación te enseña qué se puede averiguar de ti desde fuera.
          Esto es lo otro: lo que ya está en manos de quien compra bases de datos
          robadas. La diferencia importa, porque una contraseña filtrada no se
          descubre buscándote, sino teniéndote en una lista.
        </p>
      </section>

      <div className="max-w-3xl">
        <PasswordExposureCheck />
      </div>

      <div className="max-w-3xl rounded-xl border border-[#162234] bg-[#0d1420] p-5 shadow-xl">
        <h2 className="text-sm font-semibold text-slate-100">
          Esto no comprueba las contraseñas de otras personas
        </h2>
        <p className="text-xs text-slate-400 mt-2 leading-relaxed">
          Una contraseña ajena no se puede consultar: la tiene que teclear su
          dueño. Lo que sí se puede saber de un tercero, y lo hacen las
          investigaciones, es <strong className="text-slate-200">en qué
          brechas aparece su correo</strong> y{" "}
          <strong className="text-slate-200">
            si un malware le robó credenciales
          </strong>
          , que es información sobre el hecho de la exposición, nunca sobre la
          contraseña en sí. PersonMap no almacena contraseñas en ningún punto del
          expediente, y eso está impuesto por código, no por costumbre.
        </p>
      </div>
    </div>
  );
}
