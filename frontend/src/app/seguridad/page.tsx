import Link from "next/link";
import {
  ArrowLeft,
  ShieldAlert,
  ShieldCheck,
  Lock,
} from "lucide-react";
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
    <div className="w-full space-y-6">
      <div className="flex items-center gap-2">
        <Link
          href="/"
          className="text-xs font-mono text-slate-400 hover:text-sky-400 flex items-center gap-1.5 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" /> Volver al inicio
        </Link>
      </div>

      {/* Header Banner - Spans Full Width */}
      <section className="panel-card border border-[#162234] bg-[#0d1420] p-5 sm:p-6 shadow-xl relative overflow-hidden">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-amber-500/5 blur-2xl" />
        <div className="pointer-events-none absolute -right-6 top-10 h-32 w-32 rounded-full bg-sky-500/5 blur-xl" />

        <div className="relative flex flex-col xl:flex-row xl:items-center justify-between gap-5">
          <div className="space-y-2 max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 font-mono text-xs font-medium">
                <ShieldAlert className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Módulo de Autodefensa</span>
              </div>
              <span className="text-slate-600 hidden sm:inline">|</span>
              <span className="text-xs font-mono text-slate-400">Auditoría local de credenciales</span>
            </div>

            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-100 font-sans">
              Comprueba tu propia exposición
            </h1>

            <p className="text-sm text-slate-400 leading-relaxed">
              Una investigación te enseña qué se puede averiguar de ti desde fuera.
              Esto es lo otro: lo que ya está en manos de quien compra bases de datos
              robadas. La diferencia importa, porque una contraseña filtrada no se
              descubre buscándote, sino teniéndote en una lista.
            </p>
          </div>

          {/* Telemetry pill badges */}
          <div className="flex flex-wrap xl:flex-col gap-2 shrink-0 font-mono text-xs">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#121a27] border border-[#1e2d42]">
              <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
              <span className="text-slate-300">k-Anonimato (SHA-1)</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#121a27] border border-[#1e2d42]">
              <span className="w-2 h-2 rounded-full bg-sky-400"></span>
              <span className="text-slate-300">Zero-Knowledge (Sin backend)</span>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#121a27] border border-[#1e2d42]">
              <span className="w-2 h-2 rounded-full bg-amber-400"></span>
              <span className="text-slate-300">Evaluación en navegador</span>
            </div>
          </div>
        </div>
      </section>

      {/* Row 1: The Interactive Checker + Ethical Scope */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch w-full">
        {/* Left: The Interactive Checker */}
        <div className="h-full">
          <PasswordExposureCheck />
        </div>

        {/* Right: Ethical Boundaries & Investigation Scope */}
        <div className="panel-card border border-[#162234] bg-[#0d1420] p-5 sm:p-6 shadow-xl h-full flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shrink-0">
                  <ShieldAlert className="w-4 h-4" aria-hidden="true" />
                </div>
                <h2 className="text-sm font-semibold text-slate-100 font-sans">
                  Esto no comprueba contraseñas ajenas
                </h2>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#131e2e] text-amber-400/90 border border-amber-500/20 shrink-0">
                Delimitación ética
              </span>
            </div>

            <div className="space-y-3 text-xs text-slate-400 leading-relaxed mt-4">
              <p>
                Una contraseña ajena no se puede consultar: la tiene que teclear su
                dueño. Lo que sí se puede saber de un tercero, y lo hacen las
                investigaciones de PersonMap, es{" "}
                <strong className="text-slate-200">
                  en qué brechas aparece su correo
                </strong>{" "}
                y{" "}
                <strong className="text-slate-200">
                  si un malware le robó credenciales
                </strong>
                , que es información sobre el hecho de la exposición pública, nunca sobre la
                contraseña en sí.
              </p>
              <p>
                Esta distinción es fundamental para una herramienta con rigor forense:
                el expediente reconstruye huella digital observable desde fuentes abiertas;
                este módulo brinda autodefensa directa a quien opera la consola.
              </p>
            </div>
          </div>

          <div className="mt-5 p-3.5 rounded-lg bg-[#0a0f18] border border-[#1a293d] flex items-start gap-2.5">
            <Lock className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="text-[11px] font-mono text-slate-400">
              <span className="text-slate-200 font-semibold block mb-0.5">
                Garantía de código y arquitectura
              </span>
              PersonMap no almacena contraseñas en ningún punto del expediente.
              No existen tablas en base de datos, cookies ni endpoints destinados a retener claves.
            </div>
          </div>
        </div>
      </div>

      {/* Row 2: Privacy Guarantee + Self-defense Protocol on the same line with equal sizes */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch w-full">
        {/* Card 1: Privacy Architecture Guarantee */}
        <div className="panel-card border border-[#162234] bg-[#0d1420] p-5 sm:p-6 shadow-xl h-full flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400 shrink-0">
                  <Lock className="w-4 h-4" aria-hidden="true" />
                </div>
                <h2 className="text-sm font-semibold text-slate-100 font-sans">
                  Garantía de privacidad por diseño
                </h2>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#131e2e] text-sky-400/90 border border-sky-500/20 shrink-0">
                k-Anonimato (SHA-1)
              </span>
            </div>

            <div className="space-y-3 my-4">
              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  1. Hash local en memoria (SHA-1)
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  La conversión criptográfica se ejecuta exclusivamente en tu navegador; la clave en texto plano jamás se transmite.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  2. Modelo k-Anonimato (5 caracteres)
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  Solo se envían los 5 primeros caracteres hexadecimales del hash (prefijo). El servicio remoto nunca conoce tu hash completo.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  3. Zero-Knowledge backend
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  Tu consulta va directo a Cloudflare / HIBP. PersonMap no intermedia, no analiza ni almacena tráfico ni credenciales.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#162234] text-[11px] font-mono text-slate-500 flex items-center justify-between">
            <span>Auditoría local en cliente</span>
            <span className="text-slate-400 font-medium">100% Efímero</span>
          </div>
        </div>

        {/* Card 2: Actionable Countermeasures (Self-Defense Protocol) */}
        <div className="panel-card border border-[#162234] bg-[#0d1420] p-5 sm:p-6 shadow-xl h-full flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
                  <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                </div>
                <h2 className="text-sm font-semibold text-slate-100 font-sans">
                  Protocolo de autodefensa
                </h2>
              </div>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#131e2e] text-emerald-400/90 border border-emerald-500/20 shrink-0">
                Mitigación inmediata
              </span>
            </div>

            <div className="space-y-3 my-4">
              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  1. Rotación inmediata
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  Cambia la contraseña en todos los servicios y plataformas donde haya sido reutilizada o compartida.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  2. Autenticación multifactor (2FA)
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  Activa verificación en dos pasos mediante aplicaciones TOTP o llaves físicas FIDO2/WebAuthn, evitando SMS.
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#0a0e16] border border-[#1a293d]">
                <div className="font-mono text-slate-200 text-xs font-semibold">
                  3. Usar gestor de contraseñas
                </div>
                <p className="mt-1 text-slate-400 text-xs leading-relaxed">
                  Genera claves largas, aleatorias y únicas para cada cuenta con un gestor confiable (Bitwarden, 1Password).
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#162234] text-[11px] font-mono text-slate-500 flex items-center justify-between">
            <span>Defensa en profundidad</span>
            <span className="text-emerald-400 font-medium">Recomendación OWASP</span>
          </div>
        </div>
      </div>
    </div>
  );
}
