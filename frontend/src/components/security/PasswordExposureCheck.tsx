"use client";

import { useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  ShieldCheck,
} from "lucide-react";
import {
  PREFIX_LENGTH,
  RANGE_ENDPOINT,
  checkPassword,
  verdictFor,
  type PwnedResult,
} from "@/lib/pwnedPasswords";

/**
 * Comprobador de contraseñas filtradas.
 *
 * **Es la única vista del proyecto que no habla del objetivo sino de quien la
 * usa**, y por eso está fuera del expediente. Un expediente responde "qué se
 * puede averiguar de esta persona desde fuera"; una contraseña no se puede
 * averiguar desde fuera, la tiene que teclear su dueño. Meterla como pestaña de
 * la investigación insinuaría que el sistema comprueba las contraseñas del
 * objetivo, que es justo lo que no hace y no debe parecer que hace.
 *
 * Nada de lo que se teclea aquí se guarda, ni se envía al backend, ni entra en
 * ninguna entidad. El estado vive en este componente y muere con él.
 */
export function PasswordExposureCheck() {
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [result, setResult] = useState<PwnedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /** Cualquier cambio invalida el resultado anterior: era de otra contraseña. */
  const onChange = (value: string) => {
    setPassword(value);
    setResult(null);
    setError(null);
  };

  const run = async () => {
    if (!password || loading) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await checkPassword(password));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo consultar el servicio.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const limpiar = () => {
    setPassword("");
    setResult(null);
    setError(null);
    inputRef.current?.focus();
  };

  const verdict = result ? verdictFor(result.count) : null;

  return (
    <div className="rounded-lg border border-[#1e293b] bg-[#0e141f] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1e293b] flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-[#151d2c] border border-[#233044] flex items-center justify-center text-amber-400 shrink-0">
          <KeyRound className="w-4.5 h-4.5" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-slate-100">
            ¿Tu contraseña está filtrada?
          </h2>
          <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
            Se compara contra las credenciales recuperadas de brechas públicas.
            La contraseña <strong className="text-slate-200">no sale de esta
            pestaña</strong>: se explica abajo por qué eso es cierto y no una
            promesa.
          </p>
        </div>
      </div>

      <div className="p-5 space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
          className="space-y-2"
        >
          <label
            htmlFor="pwd-check"
            className="block text-[10px] font-mono uppercase tracking-wider text-slate-500"
          >
            Contraseña a comprobar
          </label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Lock
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500"
                aria-hidden="true"
              />
              <input
                id="pwd-check"
                ref={inputRef}
                type={visible ? "text" : "password"}
                value={password}
                onChange={(e) => onChange(e.target.value)}
                // No se guarda, no se autocompleta y no se corrige: no es un
                // formulario de acceso y el navegador no debe tratarlo como tal.
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                placeholder="Escríbela aquí"
                className="w-full pl-9 pr-10 py-2.5 rounded-md bg-[#121824] border border-[#233044] text-sm text-slate-100 font-mono placeholder:text-slate-600 focus:outline-none focus:border-sky-500/60"
              />
              <button
                type="button"
                onClick={() => setVisible((v) => !v)}
                aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 cursor-pointer"
              >
                {visible ? (
                  <EyeOff className="w-4 h-4" aria-hidden="true" />
                ) : (
                  <Eye className="w-4 h-4" aria-hidden="true" />
                )}
              </button>
            </div>

            <button
              type="submit"
              disabled={!password || loading}
              className="px-4 py-2.5 rounded-md bg-sky-500/20 text-sky-200 border border-sky-500/40 text-xs font-mono font-semibold hover:bg-sky-500/30 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors flex items-center gap-2 whitespace-nowrap"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
              )}
              <span>Comprobar</span>
            </button>
          </div>
        </form>

        {error && (
          <p className="flex items-start gap-2 text-xs text-rose-300">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
            <span>{error}</span>
          </p>
        )}

        {result && verdict && (
          <div
            className="rounded-md border border-[#233044] bg-[#0c111a] p-4 space-y-3"
            role="status"
            aria-live="polite"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className={`text-sm font-semibold ${verdict.tone}`}>
                  {verdict.titulo}
                </p>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                  {verdict.texto}
                </p>
              </div>
              <span
                className={`shrink-0 px-2 py-1 rounded border text-[11px] font-mono ${verdict.badge}`}
              >
                {result.count === 0
                  ? "0 apariciones"
                  : `${result.count.toLocaleString("es")} ${
                      result.count === 1 ? "aparición" : "apariciones"
                    }`}
              </span>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed border-t border-[#1e293b] pt-3">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500 block mb-1">
                Qué hacer
              </span>
              {verdict.accion}
            </p>

            <button
              type="button"
              onClick={limpiar}
              className="text-[11px] font-mono text-slate-400 hover:text-slate-200 underline underline-offset-2 cursor-pointer"
            >
              Borrar la contraseña del formulario
            </button>
          </div>
        )}

        <Transparencia result={result} />
      </div>
    </div>
  );
}

/**
 * La parte didáctica: enseña literalmente lo que se envió.
 *
 * Sin esto la vista pide un acto de fe idéntico al de cualquier web que promete
 * no guardar nada. Con esto, la afirmación es comprobable: la petición está
 * escrita, y el usuario puede abrirla en la pestaña de red del navegador y ver
 * que no hay ninguna otra.
 */
function Transparencia({ result }: { result: PwnedResult | null }) {
  const prefijo = result?.prefix ?? "CBFDA";
  const ejemplo = !result;

  return (
    <details className="group">
      <summary className="cursor-pointer text-[11px] font-mono text-slate-400 hover:text-slate-200 list-none flex items-center gap-1.5">
        <span className="text-slate-600 group-open:rotate-90 transition-transform">
          &#9656;
        </span>
        Por qué la contraseña no sale de aquí
      </summary>

      <div className="mt-3 space-y-3 text-xs text-slate-400 leading-relaxed border-l-2 border-[#233044] pl-3">
        <p>
          Se calcula el SHA-1 de la contraseña en tu navegador y se envían{" "}
          <strong className="text-slate-200">
            solo los {PREFIX_LENGTH} primeros caracteres
          </strong>{" "}
          del hash. El servicio devuelve todos los hashes que empiezan igual y la
          comparación se hace aquí. A esto se le llama{" "}
          <em className="text-slate-300">k-anonimato</em>.
        </p>

        <div className="rounded bg-[#0a0e16] border border-[#1e293b] p-2.5 font-mono text-[11px] text-slate-300 overflow-x-auto">
          <p className="text-slate-500">
            {ejemplo ? "// ejemplo con una contraseña cualquiera" : "// tu consulta"}
          </p>
          <p className="mt-1">
            GET {RANGE_ENDPOINT}
            <span className="text-sky-300">{prefijo}</span>
          </p>
          {result && (
            <p className="text-slate-500 mt-1">
              &rarr; {result.candidates.toLocaleString("es")} sufijos recibidos;
              la coincidencia se buscó en tu equipo
            </p>
          )}
        </div>

        <p>
          Ese prefijo lo comparten miles de contraseñas distintas, así que el
          servicio no puede saber cuál era la tuya, y ni siquiera recibe el hash
          completo. Además se pide relleno artificial para que el tamaño de la
          respuesta tampoco delate nada.
        </p>

        <p className="flex items-start gap-1.5 text-slate-300">
          <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-px" aria-hidden="true" />
          <span>
            La petición sale directa de tu navegador al servicio:{" "}
            <strong className="text-slate-200">
              el backend de PersonMap no interviene
            </strong>
            , no recibe la contraseña y no hay nada que guardar. Compruébalo en
            la pestaña &quot;Red&quot; de las herramientas del navegador.
          </span>
        </p>
      </div>
    </details>
  );
}
