/**
 * Bandas de certeza de atribución: fuente única para toda la interfaz.
 *
 * Existe por el mismo motivo que `entityTypes.ts`: si el grafo, la explicación
 * del nodo y la pestaña de identidad calcularan cada uno sus propios umbrales,
 * el expediente acabaría contradiciéndose a sí mismo — un hallazgo pintado como
 * seguro en el mapa y listado entre los descartados dos pestañas más allá.
 *
 * **Las bandas subdividen las tres categorías del resolutor, no las cambian.**
 * El backend agrupa en confirmado (≥0.70), probable (0.40-0.70) y descartado
 * (<0.40); aquí solo se afina la lectura dentro de esos tramos:
 *
 *   Confirmado · Muy seguro · Seguro   ->  el cluster "confirmado" del resolutor
 *   Probable · Por confirmar            ->  el cluster "probable"
 *   Poco probable · Sin datos           ->  el cluster "homónimos descartados"
 *
 * Mover un umbral de aquí sin moverlo en `app/identity/resolver.py` rompe esa
 * correspondencia.
 */

import type { IdentityBreakdown } from "@/lib/types";

export interface CertaintyBand {
  id: string;
  /** Etiqueta corta, la del filtro y la del nodo. */
  label: string;
  /** Puntuación mínima de atribución para caer en esta banda. */
  min: number;
  /** Clases de la insignia del porcentaje dentro del nodo. */
  badge: string;
  /** Halo del nodo en el mapa. */
  ring: string;
  /** Punto de color del filtro. */
  dot: string;
  /** El mismo color en hexadecimal, para el SVG y el minimapa del grafo. */
  hex: string;
  /** Clases del chip cuando está activo. */
  chipActive: string;
  /** Se atenúa en el mapa: es ruido que estorba para leer lo que importa. */
  dim?: boolean;
  help: string;
  /** Titular y explicación que usa `PlainExplanation`. */
  verdict: { titulo: string; texto: string; tone: string };
}

/** Ordenadas de mayor a menor certeza. El orden es el de los filtros. */
export const CERTAINTY_BANDS: CertaintyBand[] = [
  {
    id: "verified",
    label: "Confirmado",
    min: Number.POSITIVE_INFINITY, // solo por verificación manual
    badge: "bg-emerald-500/25 text-emerald-200",
    ring: "ring-2 ring-emerald-400/60",
    dot: "bg-emerald-400",
    hex: "#34d399",
    chipActive: "bg-emerald-500 text-white border-emerald-400",
    help: "Alguien revisó este hallazgo a mano y confirmó que es de la persona.",
    verdict: {
      titulo: "Confirmado a mano",
      texto:
        "Alguien revisó este hallazgo y confirmó que pertenece a la persona. " +
        "La revisión manual manda sobre el modelo.",
      tone: "text-emerald-200",
    },
  },
  {
    id: "very_high",
    label: "Muy seguro",
    min: 0.9,
    badge: "bg-emerald-500/20 text-emerald-300",
    ring: "ring-1 ring-emerald-500/50",
    dot: "bg-emerald-400",
    hex: "#10b981",
    chipActive: "bg-emerald-600 text-white border-emerald-500",
    help: "Coinciden varias señales fuertes e independientes entre sí.",
    verdict: {
      titulo: "Es de esta persona, casi con seguridad",
      texto:
        "Coinciden varias señales fuertes e independientes entre sí. Que eso " +
        "ocurra por casualidad en alguien distinto es muy improbable.",
      tone: "text-emerald-300",
    },
  },
  {
    id: "high",
    label: "Seguro",
    min: 0.7,
    badge: "bg-teal-500/20 text-teal-300",
    ring: "ring-1 ring-teal-500/40",
    dot: "bg-teal-400",
    hex: "#2dd4bf",
    chipActive: "bg-teal-600 text-white border-teal-500",
    help: "Hay evidencia suficiente para atribuirlo, aunque no sea concluyente.",
    verdict: {
      titulo: "Es de esta persona",
      texto:
        "La evidencia basta para atribuirlo, aunque no sea concluyente. Es el " +
        "umbral a partir del cual el sistema lo da por suyo.",
      tone: "text-teal-300",
    },
  },
  {
    id: "probable",
    label: "Probable",
    min: 0.4,
    badge: "bg-amber-500/15 text-amber-300",
    ring: "ring-1 ring-amber-500/30",
    dot: "bg-amber-400",
    hex: "#fbbf24",
    chipActive: "bg-amber-600 text-white border-amber-500",
    help: "Indicios, pero no los suficientes. Conviene revisarlo a mano.",
    verdict: {
      titulo: "Probablemente sí, pero conviene comprobarlo",
      texto:
        "Hay indicios, pero no los suficientes para afirmarlo. Merece una " +
        "revisión manual antes de darlo por bueno.",
      tone: "text-amber-300",
    },
  },
  {
    // Banda especial, como "Sin datos": no la decide la puntuación sino QUÉ la
    // sostiene. Una cuenta con un alias poco común alcanza "Probable" (~49 %)
    // sin ningún otro dato, y enseñarla como suya en una demostración es
    // exponerse a un "esa no soy yo" que nada en el expediente puede rebatir.
    id: "alias_only",
    label: "Por confirmar",
    min: Number.NEGATIVE_INFINITY,
    badge: "bg-yellow-500/10 text-yellow-200/90",
    ring: "",
    dot: "bg-yellow-300/70",
    hex: "#fde68a",
    chipActive: "bg-yellow-700 text-white border-yellow-600",
    dim: true,
    help:
      "Solo coincide el alias. Es poco común, pero ningún dato demuestra que la " +
      "cuenta sea de la persona: no se muestra como suya hasta confirmarla.",
    verdict: {
      titulo: "Sin prueba: solo coincide el alias",
      texto:
        "Que el alias sea poco común hace plausible que la cuenta sea suya, pero " +
        "ningún dato lo demuestra y podría ser otra persona con el mismo alias. " +
        "No se da por suya hasta que alguien lo confirme.",
      tone: "text-yellow-200",
    },
  },
  {
    id: "unlikely",
    label: "Poco probable",
    min: 0,
    badge: "bg-orange-500/10 text-orange-300/90",
    ring: "",
    dot: "bg-orange-400/70",
    hex: "#fb923c",
    chipActive: "bg-orange-700 text-white border-orange-600",
    dim: true,
    help:
      "Se comprobaron señales y no encajaron. Lo más probable es que sea otra " +
      "persona con el mismo alias.",
    verdict: {
      titulo: "Probablemente NO es esta persona",
      texto:
        "Se pudo comparar algún dato y no encajó. Coincidir en un alias no " +
        "basta: lo más plausible es que sea alguien distinto que registró el " +
        "mismo nombre de usuario.",
      tone: "text-orange-300",
    },
  },
  {
    // Banda especial: no la decide la puntuación sino la ausencia de señales.
    id: "no_data",
    label: "Sin datos",
    min: Number.NEGATIVE_INFINITY,
    badge: "bg-slate-700/60 text-slate-400",
    ring: "",
    dot: "bg-slate-500",
    hex: "#64748b",
    chipActive: "bg-slate-600 text-white border-slate-500",
    dim: true,
    help:
      "No hubo ningún dato en común que comparar. El sistema no afirma que sea " +
      "otra persona: afirma que no lo sabe.",
    verdict: {
      titulo: "No hay con qué compararlo",
      texto:
        "No existe ningún dato en común entre la persona y este hallazgo, así " +
        "que no se pudo evaluar ni una sola señal. El sistema no está diciendo " +
        "que sea otra persona: está diciendo que no lo sabe.",
      tone: "text-slate-300",
    },
  },
];

/** Las que se muestran de entrada: se ocultan las dos de abajo. */
export const DEFAULT_VISIBLE_BANDS = new Set(
  CERTAINTY_BANDS.filter((b) => !b.dim).map((b) => b.id)
);

/**
 * Banda de un hallazgo.
 *
 * `signalsEvaluated` importa tanto como la puntuación, y es la lección de la
 * Fase 2 aplicada a la interfaz: **"no se pudo comparar" no es lo mismo que "se
 * comparó y no encajó"**. Medido sobre 1.797 entidades reales, la puntuación
 * 0.10 corresponde SIEMPRE a cero señales evaluables —el modelo se queda en su
 * probabilidad de partida porque no tiene nada— mientras que las puntuaciones
 * por debajo (0.01-0.04) son casos donde sí se comparó algo y no encajó.
 *
 * Presentar los dos como "descartado" ocultaría esa diferencia, que es
 * justamente la que el modelo tardó una fase entera en aprender a distinguir.
 */
export function bandOf(
  score: number,
  verified = false,
  breakdown?: IdentityBreakdown
): CertaintyBand {
  if (verified) return BAND.verified;

  if (breakdown?.signals_evaluated === 0 && score < 0.4) {
    return BAND.no_data;
  }

  // Solo donde habría salido "Probable": por debajo, un alias que apenas empuja
  // ya se lee bien como "Poco probable" (otra persona con el mismo alias).
  if (score >= 0.4 && score < 0.7 && onlyTheAliasSupports(breakdown)) {
    return BAND.alias_only;
  }

  return SCORED_BANDS.find((b) => score >= b.min) ?? BAND.unlikely;
}

const BAND = Object.fromEntries(CERTAINTY_BANDS.map((b) => [b.id, b])) as Record<
  string,
  CertaintyBand
>;

/** Las que decide la puntuación, de mayor a menor. */
const SCORED_BANDS = ["very_high", "high", "probable", "unlikely"].map((id) => BAND[id]);

/** ¿La especificidad del alias es lo único que empuja hacia la persona? */
function onlyTheAliasSupports(breakdown?: IdentityBreakdown): boolean {
  if (!breakdown) return false;
  const supporting = Object.entries(breakdown).filter(
    ([key, value]) => key.endsWith("_weight") && typeof value === "number" && value > 0
  );
  return supporting.length === 1 && supporting[0][0] === "alias_specificity_weight";
}
