"use client";

import { AlertCircle, Check, HelpCircle, X } from "lucide-react";
import type { IdentityBreakdown } from "@/lib/types";
import { bandOf } from "@/lib/certainty";

/**
 * El porcentaje explicado en castellano llano.
 *
 * `IdentityEvidence` ya desglosa el modelo señal a señal con sus bits de
 * log-verosimilitud, y eso es lo que hace el score auditable ante un tribunal.
 * Pero no es lo que necesita la persona a la que se le enseña su propio
 * expediente: ante un "81 %" lo primero que quiere saber es **qué encaja, qué
 * no, y qué no se ha podido comprobar**.
 *
 * Esta vista responde a eso sin mencionar bits ni Fellegi-Sunter. La técnica
 * sigue disponible justo debajo, para quien quiera auditarla.
 */

/** Cómo se cuenta cada señal en lenguaje corriente. */
const SIGNAL_PHRASES: Record<
  string,
  { yes: string; no: string; missing: string }
> = {
  name_match: {
    yes: "el nombre del perfil coincide con el de la persona",
    no: "el nombre del perfil no se parece al de la persona",
    missing: "el perfil no muestra ningún nombre que comparar",
  },
  email_match: {
    yes: "el perfil declara el mismo correo",
    no: "el correo que muestra el perfil es otro",
    missing: "no hay ningún correo visible en el perfil",
  },
  username_match: {
    yes: "usa el mismo alias",
    no: "el alias no coincide",
    missing:
      "el alias coincide, pero se encontró buscando ese alias: la coincidencia " +
      "estaba garantizada y no prueba nada",
  },
  university_match: {
    yes: "menciona la misma universidad",
    no: "la afiliación que declara es de otra institución",
    missing: "el perfil no dice dónde estudia o trabaja",
  },
  phone_match: {
    yes: "aparece el mismo teléfono",
    no: "el teléfono que figura es otro",
    missing: "no hay teléfono que comparar",
  },
  cross_link: {
    yes: "enlaza a otros perfiles ya atribuidos a la persona",
    no: "no enlaza a ninguno de los perfiles conocidos",
    missing: "el perfil no enlaza a ninguna otra cuenta",
  },
  cryptographic_proof: {
    yes: "la identidad está demostrada con una firma criptográfica",
    no: "la firma criptográfica no corresponde",
    missing: "no hay ninguna prueba criptográfica disponible",
  },
  avatar_match: {
    yes: "usa la misma foto de perfil que otra cuenta ya atribuida",
    no: "la foto de perfil es distinta",
    missing: "no tiene foto propia, o su foto es la genérica del servicio",
  },
  semantic_bio_match: {
    yes: "la biografía describe el mismo perfil aunque con otras palabras",
    no: "la biografía describe a alguien distinto",
    missing: "el perfil no tiene biografía que comparar",
  },
};

const RESERVED = new Set([
  "log_likelihood_ratio",
  "signals_evaluated",
  "scorer_version",
]);

interface Grouped {
  encaja: string[];
  noEncaja: string[];
  sinDato: string[];
}

function groupSignals(breakdown: IdentityBreakdown): Grouped {
  const out: Grouped = { encaja: [], noEncaja: [], sinDato: [] };

  for (const [key, value] of Object.entries(breakdown)) {
    if (RESERVED.has(key)) continue;
    if (key.endsWith("_weight") || key.endsWith("_applicable")) continue;
    if (typeof value !== "number") continue;

    const phrases = SIGNAL_PHRASES[key];
    if (!phrases) continue;

    const applicableRaw = breakdown[`${key}_applicable`];
    const applicable = applicableRaw === undefined ? true : Boolean(applicableRaw);

    if (!applicable) out.sinDato.push(phrases.missing);
    else if (value > 0) out.encaja.push(phrases.yes);
    else out.noEncaja.push(phrases.no);
  }

  return out;
}

/**
 * El veredicto sale de `lib/certainty`, la misma fuente que usan el nodo del
 * mapa y sus filtros. Si esta vista calculara sus propios umbrales, un hallazgo
 * podría salir "seguro" en el grafo y "probable" al pulsarlo.
 *
 * El único matiz que se añade aquí: cuando NADA encaja, el sistema no está
 * concluyendo que sea otra persona, está diciendo que no tiene con qué
 * comparar. No es lo mismo y no debe afirmarse igual.
 */
function verdictFor(band: ReturnType<typeof bandOf>) {
  return band.verdict;
}

interface Props {
  breakdown?: IdentityBreakdown;
  score: number;
  verified?: boolean;
}

export function PlainExplanation({ breakdown, score, verified = false }: Props) {
  if (!breakdown || Object.keys(breakdown).length === 0) {
    return (
      <p className="text-[11px] text-slate-400 italic">
        Este hallazgo se registró antes de que el motor guardara la explicación.
      </p>
    );
  }

  const { encaja, noEncaja, sinDato } = groupSignals(breakdown);
  const band = bandOf(
    score,
    verified,
    typeof breakdown.signals_evaluated === "number"
      ? breakdown.signals_evaluated
      : undefined
  );
  const v = verdictFor(band);
  const pct = Math.round(score * 100);

  return (
    <div className="space-y-3 text-[11px]">
      <div className="p-2.5 rounded-md bg-[#0c111a] border border-[#1e293b]">
        <p className={`font-semibold ${v.tone}`}>
          {pct}% · {v.titulo}
        </p>
        <p className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mt-0.5">
          nivel: {band.label}
        </p>
        <p className="text-slate-400 mt-1 leading-snug">{v.texto}</p>
      </div>

      {encaja.length > 0 && (
        <Block
          icon={<Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-px" />}
          titulo="Lo que encaja"
          items={encaja}
          itemClass="text-slate-300"
        />
      )}

      {noEncaja.length > 0 && (
        <Block
          icon={<X className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-px" />}
          titulo="Lo que no encaja"
          items={noEncaja}
          itemClass="text-slate-300"
        />
      )}

      {sinDato.length > 0 && (
        <Block
          icon={<HelpCircle className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-px" />}
          titulo="Lo que queda en duda"
          items={sinDato}
          itemClass="text-slate-400"
        />
      )}

      {encaja.length === 0 && noEncaja.length === 0 && (
        <p className="flex items-start gap-1.5 text-slate-400 leading-snug">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" />
          <span>
            No hubo <strong className="text-slate-200">ninguna señal comparable</strong>:
            no existe ningún dato en común entre la persona y este hallazgo. El
            sistema no afirma nada, se queda en la duda de partida.
          </span>
        </p>
      )}
    </div>
  );
}

function Block({
  icon,
  titulo,
  items,
  itemClass,
}: {
  icon: React.ReactNode;
  titulo: string;
  items: string[];
  itemClass: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mb-1">
        {titulo}
      </p>
      <ul className="space-y-1">
        {items.map((texto) => (
          <li key={texto} className={`flex items-start gap-1.5 ${itemClass} leading-snug`}>
            {icon}
            <span>{texto}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
