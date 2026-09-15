"use client";

import { HelpCircle, Minus, Scale, TrendingDown, TrendingUp } from "lucide-react";
import type { IdentityBreakdown, LlmArbitration } from "@/lib/types";
import { AvatarThumb } from "@/components/identity/AvatarThumb";

/**
 * Explica por qué el sistema atribuye un hallazgo al objetivo.
 *
 * El motor calcula un desglose Fellegi-Sunter por entidad y, hasta ahora, lo
 * descartaba: el usuario veía un "87%" sin ninguna justificación. Aquí se
 * despliega señal a señal, con su peso en bits de log-verosimilitud, de modo
 * que el score deja de ser una caja negra y pasa a ser una afirmación
 * auditable — que es lo que hace falta para defenderlo ante un tribunal
 * académico o citarlo en un artículo.
 */

const SIGNAL_LABELS: Record<string, { label: string; help: string }> = {
  name_match: {
    label: "Nombre",
    help: "Similitud entre el nombre del objetivo y el nombre, título o biografía del perfil.",
  },
  email_match: {
    label: "Correo",
    help: "El perfil declara o contiene el correo del objetivo. Es la señal individual más concluyente.",
  },
  university_match: {
    label: "Universidad",
    help: "La afiliación institucional del objetivo aparece en la biografía o los metadatos del perfil.",
  },
  username_match: {
    label: "Alias",
    help: "El alias del objetivo coincide con el del perfil o aparece en su URL.",
  },
  phone_match: {
    label: "Teléfono",
    help: "El número del objetivo aparece en los metadatos del perfil.",
  },
  cross_link: {
    label: "Enlaces cruzados",
    help: "El perfil enlaza a otros perfiles, lo que permite encadenar identidades.",
  },
  cryptographic_proof: {
    label: "Prueba criptográfica",
    help: "Identidad demostrada mediante firma criptográfica (Keybase). Es prueba, no indicio.",
  },
  alias_specificity: {
    label: "Especificidad del alias",
    help:
      "Qué tan improbable es que otra persona tenga exactamente ese alias: cuenta su longitud y si se forma con el nombre real. Solo se evalúa cuando la cuenta se halló buscando el alias, y sola lleva como mucho a «Probable».",
  },
  avatar_match: {
    label: "Avatar",
    help: "La foto de perfil coincide perceptualmente con la de otra cuenta ya atribuida.",
  },
  semantic_bio_match: {
    label: "Biografía (semántica)",
    help: "La biografía describe el mismo perfil aunque use palabras distintas.",
  },
};

interface Props {
  breakdown?: IdentityBreakdown;
  identityScore?: number | null;
  existenceConfidence?: number | null;
  finalConfidence: number;
  compact?: boolean;
  /** Veredicto del arbitraje opcional por LLM, si esa condición estaba activa. */
  arbitration?: LlmArbitration;
  /** Avatar del hallazgo y su correlación, si la hubo. */
  avatar?: {
    url?: string;
    source?: string;
    harvested?: boolean;
    distance?: number;
    similarity?: number;
  };
}

interface Signal {
  key: string;
  label: string;
  help: string;
  gamma: number;
  weight: number;
  /** Si la señal no era evaluable, no aporta ni resta: no había dato que comparar. */
  applicable: boolean;
}

const RESERVED_KEYS = new Set([
  "log_likelihood_ratio",
  "signals_evaluated",
  "scorer_version",
]);

function parseSignals(breakdown: IdentityBreakdown): Signal[] {
  const signals: Signal[] = [];
  for (const [key, value] of Object.entries(breakdown)) {
    if (RESERVED_KEYS.has(key)) continue;
    if (key.endsWith("_weight") || key.endsWith("_applicable")) continue;
    if (typeof value !== "number") continue;

    const weight = breakdown[`${key}_weight`];
    const applicable = breakdown[`${key}_applicable`];
    const meta = SIGNAL_LABELS[key];
    signals.push({
      key,
      label: meta?.label ?? key.replace(/_/g, " "),
      help: meta?.help ?? "Señal del modelo de resolución de identidad.",
      gamma: value,
      weight: typeof weight === "number" ? weight : 0,
      // Los desgloses antiguos no traen la marca; se asumen evaluables.
      applicable: applicable === undefined ? true : Boolean(applicable),
    });
  }
  // Las evaluables primero, y dentro de ellas las que más empujan la decisión.
  return signals.sort((a, b) => {
    if (a.applicable !== b.applicable) return a.applicable ? -1 : 1;
    return Math.abs(b.weight) - Math.abs(a.weight);
  });
}

export function IdentityEvidence({
  breakdown,
  identityScore,
  existenceConfidence,
  finalConfidence,
  compact = false,
  arbitration,
  avatar,
}: Props) {
  if (!breakdown || Object.keys(breakdown).length === 0) {
    return (
      <p className="text-[11px] text-slate-400 italic">
        Este hallazgo no tiene desglose de atribución. Se registró antes de que el
        motor persistiera la evidencia del modelo.
      </p>
    );
  }

  const signals = parseSignals(breakdown);
  const evaluable = signals.filter((s) => s.applicable);
  // Coincide lo que empuja hacia la persona, no cualquier acuerdo parcial: un
  // alias poco específico tiene γ > 0 y aun así resta.
  const supporting = evaluable.filter((s) => s.weight > 0);
  const llr = breakdown.log_likelihood_ratio;

  return (
    <div className="space-y-2.5">
      {!compact && (
        <div className="flex items-start gap-1.5">
          <HelpCircle className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-[11px] text-slate-300 leading-snug">
            {supporting.length > 0 ? (
              <>
                Se atribuye a la persona investigada porque{" "}
                <span className="text-slate-100 font-semibold">
                  {supporting.length} de {evaluable.length} señales evaluables
                </span>{" "}
                coinciden: {supporting.map((s) => s.label.toLowerCase()).join(", ")}.
              </>
            ) : evaluable.length === 0 ? (
              <>
                No hubo <span className="text-slate-100 font-semibold">ninguna señal evaluable</span>:
                no existe dato en común que comparar entre el objetivo y este hallazgo.
                El modelo no afirma nada, se queda en su probabilidad a priori.
              </>
            ) : (
              <>
                Ninguna de las {evaluable.length} señales evaluables coincidió. La
                confianza mostrada procede de la herramienta que lo descubrió, no
                de la atribución de identidad.
              </>
            )}
          </p>
        </div>
      )}

      <ul className="space-y-1">
        {signals.map((s) => (
          <SignalRow key={s.key} signal={s} />
        ))}
      </ul>

      <div className="pt-2 border-t border-[#1e293b] space-y-1 text-[10px] font-mono">
        {typeof llr === "number" && (
          <Row
            label="Log-verosimilitud total"
            value={`${llr > 0 ? "+" : ""}${llr.toFixed(2)} bits`}
            help="Suma de los pesos de las señales evaluables. Positivo apoya que sea la misma persona; negativo, lo contrario. Las señales sin dato aportan 0."
          />
        )}
        {typeof identityScore === "number" && (
          <Row
            label="Atribución (¿es del objetivo?)"
            value={`${Math.round(identityScore * 100)}%`}
            help="Probabilidad posterior del modelo Fellegi-Sunter de que este perfil pertenezca a la persona investigada."
          />
        )}
        {typeof existenceConfidence === "number" && (
          <Row
            label="Detección (¿existe la cuenta?)"
            value={`${Math.round(existenceConfidence * 100)}%`}
            help="Certeza con la que la herramienta afirma que el perfil existe. Es independiente de a quién pertenece."
          />
        )}
        <Row
          label="Confianza mostrada"
          value={`${Math.round(finalConfidence * 100)}%`}
          help="El máximo de las dos anteriores; es el valor que ordena las vistas."
        />
        {typeof breakdown.scorer_version === "string" && (
          <Row
            label="Versión del modelo"
            value={breakdown.scorer_version}
            help="Identifica la calibración usada. Las puntuaciones solo son comparables entre investigaciones con la misma versión."
          />
        )}
      </div>

      {avatar?.url && <AvatarEvidence avatar={avatar} />}

      {arbitration && <ArbitrationNote arbitration={arbitration} />}
    </div>
  );
}

/**
 * La imagen que sostiene la señal de avatar.
 *
 * La correlación visual ya ocurría y movía la puntuación, pero el usuario nunca
 * veía las fotos ni sabía que había pasado. Es la evidencia más persuasiva que
 * produce el sistema —"estas dos cuentas usan la misma foto"— y estaba oculta
 * detrás de un número.
 */
function AvatarEvidence({
  avatar,
}: {
  avatar: NonNullable<Props["avatar"]>;
}) {
  const correlado = typeof avatar.distance === "number";

  return (
    <div className="mt-2 p-2.5 rounded border border-[#1e293b] bg-[#0c111a] flex items-start gap-3">
      <AvatarThumb
        url={avatar.url as string}
        distance={avatar.distance}
        source={avatar.source}
        size="lg"
      />
      <div className="min-w-0 text-[11px]">
        <p className="text-slate-200 font-semibold">
          {correlado
            ? "Misma foto de perfil que otra cuenta"
            : "Foto de perfil localizada"}
        </p>
        {correlado ? (
          <p className="text-slate-400 mt-0.5 leading-snug">
            <span className="font-mono text-amber-300">
              {avatar.distance} bit{avatar.distance === 1 ? "" : "s"}
            </span>{" "}
            de diferencia entre los dos hashes perceptuales
            {avatar.distance === 0 ? " (imagen idéntica)" : ""}. Reutilizar la misma
            foto permite enlazar cuentas que no comparten ni alias ni correo.
          </p>
        ) : (
          <p className="text-slate-400 mt-0.5 leading-snug">
            Sin coincidencia con otras cuentas del expediente. Los avatares por
            defecto se descartan antes de comparar: son idénticos entre personas
            distintas y no probarían nada.
          </p>
        )}
        <p className="text-slate-500 mt-1 font-mono text-[10px]">
          origen: {avatar.source || "hallazgo"}
          {avatar.harvested ? " · cosecha activa" : " · expuesto por la plataforma"}
        </p>
      </div>
    </div>
  );
}

const VERDICT_COPY: Record<
  LlmArbitration["verdict"],
  { label: string; className: string }
> = {
  match: {
    label: "sí es del objetivo",
    className: "border-emerald-500/30 bg-emerald-500/5 text-emerald-300",
  },
  no_match: {
    label: "no es del objetivo",
    className: "border-rose-500/30 bg-rose-500/5 text-rose-300",
  },
  uncertain: {
    label: "no concluyente",
    className: "border-slate-600 bg-[#0c111a] text-slate-300",
  },
};

/**
 * Veredicto del arbitraje opcional por LLM.
 *
 * Se muestra siempre que exista, y junto a la puntuación del modelo, nunca en su
 * lugar: un juicio de caja negra que mueve un hallazgo de "descartado" a
 * "confirmado" sin dejar ver qué dijo el modelo y qué dijo la IA sería
 * exactamente lo contrario de lo que esta herramienta enseña.
 */
function ArbitrationNote({ arbitration }: { arbitration: LlmArbitration }) {
  const copy = VERDICT_COPY[arbitration.verdict] ?? VERDICT_COPY.uncertain;

  return (
    <div className={`mt-2 p-2.5 rounded border text-[11px] ${copy.className}`}>
      <div className="flex items-start gap-1.5">
        <Scale className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-semibold">
            Arbitraje por IA: {copy.label}
            {typeof arbitration.applied_score === "number" && (
              <span className="font-mono font-normal opacity-80">
                {" "}
                ({Math.round(arbitration.model_score * 100)}% del modelo →{" "}
                {Math.round(arbitration.applied_score * 100)}% efectivo para agrupar)
              </span>
            )}
          </p>
          {arbitration.rationale && (
            <p className="opacity-90 mt-0.5 leading-snug">{arbitration.rationale}</p>
          )}
          <p className="opacity-60 mt-1 font-mono text-[10px]">
            Modelo: {arbitration.model} · condición opcional y no determinista; la
            puntuación del scorer no se modifica.
          </p>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <div className="flex items-center justify-between gap-2" title={help}>
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200 font-semibold">{value}</span>
    </div>
  );
}

function SignalRow({ signal }: { signal: Signal }) {
  const { label, help, gamma, weight, applicable } = signal;

  // Una señal no evaluable es un dato que no existe, no un desacuerdo. Se
  // muestra atenuada y sin barra: el modelo anterior la penalizaba como si el
  // perfil contradijera al objetivo, que es el fallo que hundía la puntuación
  // de cualquier hallazgo con pocos datos en común.
  if (!applicable) {
    return (
      <li
        className="flex items-center gap-2 text-[11px] opacity-45"
        title={`${help}\n\nNo evaluable: no hay dato que comparar en este hallazgo.`}
      >
        <Minus className="w-3 h-3 shrink-0 text-slate-500" aria-hidden="true" />
        <span className="w-32 shrink-0 truncate text-slate-400">{label}</span>
        <span className="flex-1 text-slate-500 italic">sin dato que comparar</span>
        <span className="w-16 text-right font-mono text-slate-500 shrink-0">0.0 b</span>
      </li>
    );
  }

  const agrees = gamma > 0;
  const Icon = weight > 0 ? TrendingUp : weight < 0 ? TrendingDown : Minus;
  const tone = agrees ? "text-emerald-300" : weight < 0 ? "text-rose-400/70" : "text-slate-400";

  // La barra representa el grado de acuerdo, no el peso: el peso puede ser
  // negativo y no tendría sentido dibujarlo como longitud.
  const pct = Math.round(gamma * 100);

  return (
    <li className="flex items-center gap-2 text-[11px]" title={help}>
      <Icon className={`w-3 h-3 shrink-0 ${tone}`} aria-hidden="true" />
      <span className={`w-32 shrink-0 truncate ${agrees ? "text-slate-200" : "text-slate-400"}`}>
        {label}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-[#161f2e] overflow-hidden min-w-[40px]">
        <div
          className={`h-full rounded-full ${agrees ? "bg-emerald-400/70" : "bg-slate-700"}`}
          style={{ width: `${Math.max(pct, agrees ? 6 : 0)}%` }}
        />
      </div>
      <span className="w-11 text-right font-mono text-slate-400 shrink-0">{pct}%</span>
      <span
        className={`w-16 text-right font-mono shrink-0 ${
          weight > 0 ? "text-emerald-400" : "text-rose-400/70"
        }`}
      >
        {weight > 0 ? "+" : ""}
        {weight.toFixed(1)} b
      </span>
    </li>
  );
}
