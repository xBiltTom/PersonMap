"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkHealth, createInvestigation } from "@/lib/api";
import type { Strategy } from "@/lib/types";
import {
  User,
  Mail,
  AtSign,
  Phone,
  FileText,
  GraduationCap,
  Sparkles,
  ArrowRight,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";

/**
 * Las cuatro opciones del selector de motor.
 *
 * `hybrid` se añadió en la Fase 3 como TERCERA estrategia, no como reemplazo:
 * si el motor de reglas corriera siempre, `rule_based` y `agentic` dejarían de
 * ser condiciones experimentales independientes y la comparativa del artículo
 * perdería su contraste más limpio.
 */
const STRATEGIES: Array<{
  id: Strategy;
  label: string;
  help: string;
  needsLlm: boolean;
}> = [
  {
    id: "auto",
    label: "Automático",
    help: "Usa el agente IA si hay un LLM configurado en el backend; si no, el motor por reglas.",
    needsLlm: false,
  },
  {
    id: "rule_based",
    label: "Reglas estáticas (sin IA)",
    help: "Barrido heurístico determinista con pivoteo por reglas. Reproducible y sin coste de tokens: es la condición de control del experimento.",
    needsLlm: false,
  },
  {
    id: "agentic",
    label: "Agente autónomo IA",
    help: "El LLM planifica y despacha todas las herramientas por su cuenta, sin barrido previo. Es el brazo opuesto al de reglas.",
    needsLlm: true,
  },
  {
    id: "hybrid",
    label: "Híbrido (reglas + refinamiento IA)",
    help: "Primero el barrido heurístico completo; después el LLM solo pide lo que quedó sin cubrir, sin repetir ninguna consulta ya hecha.",
    needsLlm: true,
  },
];

export function InvestigationForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [phone, setPhone] = useState("");
  const [dni, setDni] = useState("");
  const [university, setUniversity] = useState("");
  const [description, setDescription] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("auto");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selfConsent, setSelfConsent] = useState(false);

  // Si el backend no tiene LLM, las estrategias que dependen de él degradan al
  // motor de reglas. Avisarlo ANTES de lanzar evita la situación de creer que se
  // está midiendo una condición experimental y estar midiendo otra.
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkHealth()
      .then((h) => {
        if (!cancelled) setAiEnabled(h.ai_enabled);
      })
      .catch(() => {
        // El estado del backend ya lo reporta el Navbar; aquí basta con no
        // afirmar nada sobre el LLM.
        if (!cancelled) setAiEnabled(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedStrategy =
    STRATEGIES.find((s) => s.id === strategy) ?? STRATEGIES[0];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const hasIdentifier =
      fullName.trim() ||
      email.trim() ||
      username.trim() ||
      phone.trim() ||
      dni.trim();

    if (!hasIdentifier) {
      setError("Ingresa al menos un dato identificador del objetivo (nombre, correo, usuario, teléfono o DNI).");
      return;
    }

    setLoading(true);

    try {
      const inv = await createInvestigation({
        target: {
          full_name: fullName.trim() || null,
          email: email.trim() || null,
          username: username.trim() || null,
          phone: phone.trim() || null,
          dni: dni.trim() || null,
          university: university.trim() || null,
          description: description.trim() || null,
        },
        strategy,
        self_consent: selfConsent,
      });

      router.push(`/investigation/${inv.id}`);
    } catch (err: any) {
      setError(err.message || "Error al despachar la investigación.");
      setLoading(false);
    }
  };

  return (
    <div className="panel-card p-6 shadow-xl relative overflow-hidden">
      <div className="flex items-center justify-between pb-5 border-b border-[#1e293b] mb-6">
        <div>
          <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span>
            Iniciar Nueva Investigación
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Ingresa los identificadores conocidos del objetivo. El motor pivotea desde al menos 1 dato.
          </p>
        </div>

        <div className="flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded bg-[#182334] text-slate-300 border border-[#2b3a52]">
          <span>Estrategia:</span>
          <span className="text-sky-400 font-semibold">{selectedStrategy.label}</span>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-3.5 rounded-md bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Core Primary Inputs */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <User className="w-3.5 h-3.5 text-sky-400" />
              Nombre Completo
            </label>
            <input
              type="text"
              placeholder="Ej: Carlos Eduardo Mendoza"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-sky-400" />
              Correo Institucional o Personal
            </label>
            <input
              type="email"
              placeholder="Ej: alumno@uni.edu.pe o gmail"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <AtSign className="w-3.5 h-3.5 text-sky-400" />
              Alias / Nombre de Usuario
            </label>
            <input
              type="text"
              placeholder="Ej: cmendoza_dev"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <GraduationCap className="w-3.5 h-3.5 text-sky-400" />
              Universidad / Facultad
            </label>
            <input
              type="text"
              placeholder="Ej: UNI, UNMSM, PUCP..."
              value={university}
              onChange={(e) => setUniversity(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-sky-400" />
              DNI (Perú)
            </label>
            <input
              type="text"
              placeholder="8 dígitos numéricos"
              value={dni}
              onChange={(e) => setDni(e.target.value)}
              maxLength={8}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>
        </div>

        {/* Toggle Advanced / Context details */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs font-mono text-slate-400 hover:text-sky-400 flex items-center gap-1.5 py-1 transition-colors"
          >
            <SlidersHorizontal className="w-3 h-3" />
            <span>
              {showAdvanced
                ? "Ocultar parámetros avanzados"
                : "Añadir teléfono, contexto, elegir motor y consentimiento"}
            </span>
          </button>
        </div>

        {showAdvanced && (
          <div className="p-4 rounded-md bg-[#0d121c] border border-[#1e293b] space-y-4 animate-fade-in">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                  <Phone className="w-3.5 h-3.5 text-sky-400" />
                  Teléfono / Móvil
                </label>
                <input
                  type="tel"
                  placeholder="Ej: +51 987654321"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
                />
              </div>

              <div>
                <label
                  htmlFor="strategy-select"
                  className="block text-xs font-mono text-slate-300 mb-1.5"
                >
                  Modo de Orquestación
                </label>
                <select
                  id="strategy-select"
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value as Strategy)}
                  aria-describedby="strategy-help"
                  className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                >
                  {STRATEGIES.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </select>

                <p id="strategy-help" className="text-[11px] text-slate-400 mt-1.5 leading-relaxed">
                  {selectedStrategy.help}
                </p>

                {selectedStrategy.needsLlm && aiEnabled === false && (
                  <p className="text-[11px] text-amber-300 mt-1.5 flex items-start gap-1.5">
                    <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
                    <span>
                      No hay LLM configurado en el backend, así que esta estrategia
                      degradará al motor de reglas. Quedará registrada como tal en la
                      comparativa, no como IA.
                    </span>
                  </p>
                )}
              </div>
            </div>

            {/* Consentimiento para las fuentes que revelan a un tercero a quién
                se investiga. Va aquí, junto al motor, y no escondido: es la
                única casilla del formulario que cambia qué herramientas se
                ejecutan, y el marco pedagógico del proyecto es auditar la propia
                huella, no la de otra persona. */}
            <div className="p-3 rounded-md bg-[#160d0d] border border-red-500/25">
              <label
                htmlFor="self-consent"
                className="flex items-start gap-2.5 cursor-pointer"
              >
                <input
                  id="self-consent"
                  type="checkbox"
                  checked={selfConsent}
                  onChange={(e) => setSelfConsent(e.target.checked)}
                  className="mt-0.5 w-3.5 h-3.5 shrink-0 accent-red-500 cursor-pointer"
                />
                <span className="min-w-0">
                  <span className="text-xs font-mono text-red-200 flex items-center gap-1.5">
                    <ShieldAlert className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    Estoy investigando mi propia identidad
                  </span>
                  <span className="block text-[11px] text-slate-400 mt-1 leading-relaxed">
                    Habilita la consulta de registros de <strong className="text-slate-300">infostealer</strong>{" "}
                    (equipos infectados cuyas contraseñas guardadas fueron robadas en
                    texto claro). Esa consulta envía el correo o el alias a un
                    servicio externo, así que solo debe hacerse sobre uno mismo o con
                    permiso explícito. Sin marcarla, esa fuente no se ejecuta.
                  </span>
                </span>
              </label>
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                Descripción de Contexto (Opcional - enriquecimiento semántico del Agente IA)
              </label>
              <textarea
                rows={2}
                placeholder="Ej: Estudiante de VIII ciclo, suele subir proyectos en GitHub sobre seguridad y publica artículos de investigación en congresos."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
              />
            </div>
          </div>
        )}

        <div className="pt-3 flex items-center justify-between">
          <p className="text-[11px] text-slate-500 font-mono">
            * Consulta exclusivamente fuentes de acceso público bajo consentimiento ético.
          </p>

          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 px-5 py-2.5 rounded-md bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-mono font-semibold transition-all shadow-lg shadow-sky-950/50"
          >
            {loading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                <span>Despachando...</span>
              </>
            ) : (
              <>
                <span>Desplegar Reconocimiento</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
