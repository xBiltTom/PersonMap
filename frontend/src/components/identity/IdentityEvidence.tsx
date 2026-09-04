"use client";

import { HelpCircle, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { IdentityBreakdown } from "@/lib/types";

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
  identityScore?: number;
  finalConfidence: number;
  compact?: boolean;
}

interface Signal {
  key: string;
  label: string;
  help: string;
  gamma: number;
  weight: number;
}

function parseSignals(breakdown: IdentityBreakdown): Signal[] {
  const signals: Signal[] = [];
  for (const [key, value] of Object.entries(breakdown)) {
    if (key === "log_likelihood_ratio" || key.endsWith("_weight")) continue;
    if (typeof value !== "number") continue;

    const weight = breakdown[`${key}_weight`];
    const meta = SIGNAL_LABELS[key];
    signals.push({
      key,
      label: meta?.label ?? key.replace(/_/g, " "),
      help: meta?.help ?? "Señal del modelo de resolución de identidad.",
      gamma: value,
      weight: typeof weight === "number" ? weight : 0,
    });
  }
  // Primero lo que más empuja la decisión, en cualquiera de los dos sentidos.
  return signals.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
}

export function IdentityEvidence({
  breakdown,
  identityScore,
  finalConfidence,
  compact = false,
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
  const supporting = signals.filter((s) => s.gamma > 0);
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
                  {supporting.length} señal(es)
                </span>{" "}
                coinciden: {supporting.map((s) => s.label.toLowerCase()).join(", ")}.
              </>
            ) : (
              <>
                Ninguna señal del modelo coincidió. La confianza mostrada procede
                únicamente de la herramienta que lo descubrió, no de la atribución
                de identidad.
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
            help="Suma de los pesos. Positivo apoya que sea la misma persona; negativo, lo contrario."
          />
        )}
        {typeof identityScore === "number" && (
          <Row
            label="Score de atribución"
            value={`${Math.round(identityScore * 100)}%`}
            help="Probabilidad posterior del modelo de que este perfil pertenezca al objetivo."
          />
        )}
        <Row
          label="Confianza mostrada"
          value={`${Math.round(finalConfidence * 100)}%`}
          help="Máximo entre la confianza de detección de la herramienta y el score de atribución."
        />
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
  const { label, help, gamma, weight } = signal;
  const agrees = gamma > 0;
  const Icon = weight > 0 ? TrendingUp : weight < 0 ? TrendingDown : Minus;
  const tone = agrees
    ? "text-emerald-300"
    : weight < 0
    ? "text-slate-500"
    : "text-slate-400";

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
          weight > 0 ? "text-emerald-400" : "text-slate-500"
        }`}
      >
        {weight > 0 ? "+" : ""}
        {weight.toFixed(1)} b
      </span>
    </li>
  );
}
