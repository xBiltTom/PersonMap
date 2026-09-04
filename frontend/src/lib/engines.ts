/**
 * Presentación de los motores de orquestación y de sus dos capas.
 *
 * Fuente única, igual que `entityTypes.ts`: la duplicación divergente de
 * categorías fue la causa raíz de que capacidades del backend quedaran
 * invisibles en la interfaz. Al añadir un motor nuevo basta con registrarlo
 * aquí para que la cabecera del expediente, la tabla de hallazgos y la
 * comparativa lo recojan.
 */

import type { EngineId, EngineLayer, InvestigationMetrics } from "@/lib/types";

export interface EngineMeta {
  label: string;
  /** Explicación breve; se usa como `title`. */
  description: string;
  /** Clases del badge (texto + fondo + borde). */
  badge: string;
}

export const ENGINE_META: Record<EngineId, EngineMeta> = {
  rules: {
    label: "Motor por reglas",
    description:
      "Barrido heurístico determinista con pivoteo por reglas. Sin IA: reproducible y sin coste de tokens.",
    badge: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  },
  agentic: {
    label: "Agente autónomo IA",
    description:
      "El LLM planificó y despachó las herramientas por su cuenta, sin barrido heurístico previo.",
    badge: "bg-purple-500/10 text-purple-300 border-purple-500/30",
  },
  hybrid: {
    label: "Híbrido (reglas + IA)",
    description:
      "Barrido heurístico completo y, después, refinamiento por IA solo de lo que quedó sin cubrir.",
    badge: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  },
};

export const LAYER_META: Record<EngineLayer, { label: string; short: string; badge: string; description: string }> = {
  heuristic: {
    label: "Capa 1 · heurística",
    short: "H",
    badge: "bg-sky-500/10 text-sky-300 border-sky-500/30",
    description: "Descubierto por el barrido heurístico determinista.",
  },
  refinement: {
    label: "Capa 2 · refinamiento IA",
    short: "IA",
    badge: "bg-purple-500/10 text-purple-300 border-purple-500/30",
    description: "Descubierto por una llamada que pidió la capa de refinamiento por IA.",
  },
};

/**
 * Motor que realmente ejecutó la investigación.
 *
 * `engine_used` solo existe desde la Fase 3. Para expedientes anteriores se
 * reconstruye igual que en el backend: `auto` sin LLM configurado fue una
 * corrida del motor de reglas, por más que la estrategia pedida dijera otra cosa.
 */
export function resolveEngine(
  strategy: string | undefined,
  metrics: InvestigationMetrics | undefined
): EngineId {
  const recorded = metrics?.engine_used;
  if (recorded && recorded in ENGINE_META) return recorded;

  if (strategy === "rule_based") return "rules";
  if (strategy === "hybrid") return metrics?.ai_enhanced ? "hybrid" : "rules";
  if (strategy === "agentic" || strategy === "auto") {
    return metrics?.ai_enhanced ? "agentic" : "rules";
  }
  return "rules";
}
