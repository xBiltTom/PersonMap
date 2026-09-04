"use client";

import { useState } from "react";
import { CheckCircle2, ClipboardList, Loader2, Send, AlertTriangle } from "lucide-react";
import { createSurvey } from "@/lib/api";

/**
 * Cuestionario de concientización.
 *
 * Es la **variable dependiente del estudio**: mide el delta entre la percepción
 * de exposición que el estudiante tenía antes de ver su expediente y la que
 * tiene después. Hasta ahora esto era una maqueta muerta —radios sin `value`,
 * sin estado, sin envío— de modo que el proyecto no capturaba ni un solo dato
 * de su propia métrica pedagógica pese a tener el backend completo.
 *
 * Se sitúa dentro del informe de una investigación concreta (y no en la página
 * global de métricas) porque el momento pedagógico es justo después de que la
 * persona ve su propia huella digital.
 */

const AWARENESS_SCALE = [
  { value: 1, label: "Nada expuesta" },
  { value: 2, label: "Poco" },
  { value: 3, label: "Algo" },
  { value: 4, label: "Bastante" },
  { value: 5, label: "Muy expuesta" },
];

export function AwarenessSurveyForm({ investigationId }: { investigationId: string }) {
  const [pre, setPre] = useState<number | null>(null);
  const [post, setPost] = useState<number | null>(null);
  const [knewCommitLeak, setKnewCommitLeak] = useState<boolean | null>(null);
  const [reusedAlias, setReusedAlias] = useState<boolean | null>(null);
  const [willChange, setWillChange] = useState<boolean | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete =
    pre !== null &&
    post !== null &&
    knewCommitLeak !== null &&
    reusedAlias !== null &&
    willChange !== null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!complete || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await createSurvey({
        investigation_id: investigationId,
        pre_awareness: pre,
        post_awareness: post,
        knew_commit_leak: knewCommitLeak,
        reused_alias: reusedAlias,
        will_change_habits: willChange,
      });
      setSubmitted(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo registrar la respuesta");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    const delta = (post ?? 0) - (pre ?? 0);
    return (
      <div className="panel-card p-6 border border-emerald-500/30 print:hidden">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" aria-hidden="true" />
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Respuesta registrada. Gracias.
            </h3>
            <p className="text-xs text-slate-400 mt-1 max-w-lg leading-relaxed">
              {delta > 0 ? (
                <>
                  Tu percepción de exposición subió{" "}
                  <span className="text-emerald-300 font-semibold">
                    {delta} punto{delta === 1 ? "" : "s"}
                  </span>{" "}
                  tras ver el expediente. Ese delta es exactamente lo que este
                  estudio mide: cuánto cambia la conciencia del riesgo al ver la
                  propia huella digital reconstruida.
                </>
              ) : delta === 0 ? (
                <>
                  Tu percepción no cambió: ya sabías cuánta información tuya es
                  pública. Ese dato también es relevante para el estudio.
                </>
              ) : (
                <>
                  Tu percepción de exposición bajó tras ver el expediente. Es un
                  resultado poco habitual y valioso para el análisis.
                </>
              )}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="panel-card p-6 space-y-5 print:hidden"
      aria-labelledby="survey-heading"
    >
      <div className="flex items-start gap-2.5 pb-3 border-b border-[#1e293b]">
        <ClipboardList className="w-4 h-4 text-purple-300 mt-0.5 shrink-0" aria-hidden="true" />
        <div>
          <h3 id="survey-heading" className="text-sm font-semibold text-slate-100">
            Cuestionario de Concientización
          </h3>
          <p className="text-xs text-slate-400 mt-0.5 max-w-2xl leading-relaxed">
            Cinco preguntas anónimas. Miden cuánto cambia tu percepción del riesgo
            al ver tu propia huella digital, y son los datos que sostienen el
            estudio. No se guarda ningún dato identificativo tuyo.
          </p>
        </div>
      </div>

      <ScaleQuestion
        legend="1. ANTES de ver este expediente, ¿cuán expuesta creías que estaba tu información pública?"
        name="pre_awareness"
        value={pre}
        onChange={setPre}
      />

      <ScaleQuestion
        legend="2. DESPUÉS de verlo, ¿cuán expuesta crees que está realmente?"
        name="post_awareness"
        value={post}
        onChange={setPost}
      />

      <BooleanQuestion
        legend="3. ¿Sabías que los commits públicos de Git revelan el correo con el que configuraste tu cuenta?"
        name="knew_commit_leak"
        value={knewCommitLeak}
        onChange={setKnewCommitLeak}
        yesLabel="Sí, ya lo sabía"
        noLabel="No, lo creía privado"
      />

      <BooleanQuestion
        legend="4. ¿Reutilizas el mismo alias en cuentas académicas, de ocio y redes sociales?"
        name="reused_alias"
        value={reusedAlias}
        onChange={setReusedAlias}
        yesLabel="Sí, en la mayoría"
        noLabel="No, los mantengo separados"
      />

      <BooleanQuestion
        legend="5. Tras ver tu mapa digital, ¿modificarás tus hábitos de privacidad?"
        name="will_change_habits"
        value={willChange}
        onChange={setWillChange}
        yesLabel="Sí, haré cambios"
        noLabel="No lo veo necesario"
      />

      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 p-3 rounded-md bg-rose-500/10 border border-rose-500/25 text-rose-300 text-xs"
        >
          <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex items-center justify-between gap-4 pt-1">
        <p className="text-[11px] text-slate-400">
          {complete
            ? "Todo listo para enviar."
            : "Responde las cinco preguntas para poder enviar."}
        </p>
        <button
          type="submit"
          disabled={!complete || submitting}
          className="flex items-center gap-2 px-4 py-2 rounded-md bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-mono font-semibold transition-colors cursor-pointer"
        >
          {submitting ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              Enviando...
            </>
          ) : (
            <>
              <Send className="w-3.5 h-3.5" aria-hidden="true" />
              Enviar respuesta
            </>
          )}
        </button>
      </div>
    </form>
  );
}

function ScaleQuestion({
  legend,
  name,
  value,
  onChange,
}: {
  legend: string;
  name: string;
  value: number | null;
  onChange: (v: number) => void;
}) {
  return (
    <fieldset className="p-3.5 rounded bg-[#0c111a] border border-[#1e293b]">
      <legend className="text-xs font-semibold text-slate-200 px-1">{legend}</legend>
      <div className="flex flex-wrap gap-2 mt-2.5">
        {AWARENESS_SCALE.map((opt) => {
          const id = `${name}-${opt.value}`;
          const selected = value === opt.value;
          return (
            <label
              key={opt.value}
              htmlFor={id}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-[11px] font-mono cursor-pointer transition-colors ${
                selected
                  ? "bg-purple-500/25 text-purple-100 border-purple-400/60 font-semibold"
                  : "bg-[#131b26] text-slate-300 border-[#233044] hover:border-purple-500/40"
              }`}
            >
              <input
                type="radio"
                id={id}
                name={name}
                value={opt.value}
                checked={selected}
                onChange={() => onChange(opt.value)}
                className="sr-only"
              />
              <span className="font-bold">{opt.value}</span>
              <span className="opacity-80">{opt.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function BooleanQuestion({
  legend,
  name,
  value,
  onChange,
  yesLabel,
  noLabel,
}: {
  legend: string;
  name: string;
  value: boolean | null;
  onChange: (v: boolean) => void;
  yesLabel: string;
  noLabel: string;
}) {
  const options: Array<{ v: boolean; label: string }> = [
    { v: true, label: yesLabel },
    { v: false, label: noLabel },
  ];

  return (
    <fieldset className="p-3.5 rounded bg-[#0c111a] border border-[#1e293b]">
      <legend className="text-xs font-semibold text-slate-200 px-1">{legend}</legend>
      <div className="flex flex-wrap gap-2 mt-2.5">
        {options.map((opt) => {
          const id = `${name}-${opt.v}`;
          const selected = value === opt.v;
          return (
            <label
              key={String(opt.v)}
              htmlFor={id}
              className={`px-3 py-1.5 rounded-md border text-[11px] font-mono cursor-pointer transition-colors ${
                selected
                  ? "bg-purple-500/25 text-purple-100 border-purple-400/60 font-semibold"
                  : "bg-[#131b26] text-slate-300 border-[#233044] hover:border-purple-500/40"
              }`}
            >
              <input
                type="radio"
                id={id}
                name={name}
                checked={selected}
                onChange={() => onChange(opt.v)}
                className="sr-only"
              />
              {opt.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
