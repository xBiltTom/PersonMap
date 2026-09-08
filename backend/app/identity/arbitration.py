"""
Arbitraje opcional por LLM de los hallazgos ambiguos.

El modelo Fellegi-Sunter deja una franja intermedia — probabilidad de
atribución entre 0.40 y 0.70 — en la que no hay evidencia suficiente para
confirmar ni para descartar. Un LLM puede leer el contexto textual (biografía,
plataforma, nombre mostrado) y aportar un juicio que las señales numéricas no
capturan.

Tres decisiones de diseño, todas deliberadas:

1. **Apagado por defecto** (`HYBRID_LLM_ARBITRATION=false`). Es no determinista:
   con él encendido, la misma investigación puede producir clusters distintos en
   dos ejecuciones. En una sustentación en vivo eso es inaceptable.
2. **Nunca sobrescribe `identity_score`.** El score persistido sigue siendo la
   salida pura del scorer, para que el histograma, la curva de calibración y la
   ablación del artículo midan el modelo y no una mezcla del modelo con un LLM.
   El veredicto se guarda aparte, en `metadata_info["llm_arbitration"]`, y el
   resolutor lo consulta como puntuación efectiva a la hora de agrupar.
3. **Siempre logueado.** Cada veredicto viaja a la consola en vivo y queda en el
   expediente con el modelo que lo emitió, la puntuación previa y su
   justificación. Un juicio de caja negra que mueve un hallazgo de "descartado" a
   "confirmado" sin dejar rastro sería exactamente lo contrario de lo que esta
   herramienta enseña.
"""

import json
import time
from typing import Any, Dict, List, Optional

import litellm

from app.core.config import settings
from app.core.events import event_bus
from app.models.entity import Entity
from app.models.target import Target

# Franja ambigua del modelo, alineada con los umbrales del resolutor.
AMBIGUOUS_LOW = 0.40
AMBIGUOUS_HIGH = 0.70

# Puntuaciones efectivas que aplica un veredicto. Se quedan justo al otro lado
# del umbral correspondiente: el arbitraje decide de qué lado cae un caso
# fronterizo, no cuánta certeza hay. Fingir un 0.99 sería el mismo atajo que se
# eliminó del avatar en la Fase 2.
VERDICT_SCORES = {"match": 0.72, "no_match": 0.38}

ARBITRATION_SYSTEM_PROMPT = (
    "Eres un analista de identidad. Recibes un objetivo y hallazgos OSINT cuya "
    "atribución quedó ambigua para el modelo probabilístico. Decide, para cada uno, "
    "si pertenece al objetivo.\n\n"
    "Reglas:\n"
    "- Coincidir en el alias NO es evidencia por sí solo: puede ser un homónimo o "
    "alguien que registró el mismo nombre de usuario.\n"
    "- Una coincidencia garantizada por cómo se buscó (el perfil contiene el alias "
    "porque se enumeró ese alias) es tautológica y no cuenta como prueba.\n"
    "- Ante la duda responde 'uncertain'. Un falso positivo acaba en el expediente "
    "de una persona concreta, y eso es peor que no concluir.\n\n"
    'Responde SOLO con JSON: {"verdicts": [{"id": "<id>", "verdict": '
    '"match|no_match|uncertain", "rationale": "<una frase>"}]}'
)


def _attribution(entity: Entity) -> float:
    if entity.identity_score is not None:
        return float(entity.identity_score)
    return float(entity.confidence or 0.0)


def select_ambiguous(entities: List[Entity], limit: int) -> List[Entity]:
    """Hallazgos en la franja ambigua, los más cercanos al umbral primero."""
    candidates = [
        e
        for e in entities
        if not e.verified and AMBIGUOUS_LOW <= _attribution(e) < AMBIGUOUS_HIGH
    ]
    candidates.sort(key=_attribution, reverse=True)
    return candidates[:limit]


def _describe(entity: Entity) -> Dict[str, Any]:
    meta = entity.metadata_info or {}
    bio = str(meta.get("bio") or meta.get("snippet") or "")[:280]
    return {
        "id": str(entity.id),
        "tipo": entity.entity_type,
        "plataforma": entity.platform,
        "valor": entity.value,
        "nombre_mostrado": entity.display_name,
        "bio": bio,
        "universidad_declarada": meta.get("university"),
        "descubierto_por": meta.get("source_tools") or [entity.source_tool],
        "score_modelo": round(_attribution(entity), 3),
    }


def _parse_verdicts(content: str) -> Dict[str, Dict[str, str]]:
    """Extrae el JSON del veredicto tolerando el envoltorio en ```json."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}

    out: Dict[str, Dict[str, str]] = {}
    for item in payload.get("verdicts", []) or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        verdict = str(item.get("verdict", "uncertain")).lower()
        if verdict not in ("match", "no_match", "uncertain"):
            verdict = "uncertain"
        out[str(item["id"])] = {
            "verdict": verdict,
            "rationale": str(item.get("rationale", ""))[:300],
        }
    return out


async def arbitrate_ambiguous(
    investigation_id: str,
    entities: List[Entity],
    target: Target,
) -> Optional[Dict[str, Any]]:
    """
    Somete la franja ambigua al LLM y anota su veredicto.

    Devuelve un resumen para las métricas, o `None` si el arbitraje está apagado
    o no había nada que arbitrar. No lanza: cualquier fallo del proveedor deja la
    investigación exactamente como estaba.
    """
    if not (settings.hybrid_llm_arbitration and settings.ai_enabled):
        return None

    candidates = select_ambiguous(entities, settings.hybrid_arbitration_max_entities)
    if not candidates:
        return None

    await event_bus.publish(investigation_id, {
        "type": "log",
        "phase": "hybrid_arbitration",
        "layer": "refinement",
        "message": (
            f"Arbitraje IA activado (opcional, no determinista): {len(candidates)} "
            f"hallazgos en la franja ambigua {AMBIGUOUS_LOW:.2f}-{AMBIGUOUS_HIGH:.2f} "
            f"se someten al modelo [{settings.llm_model}]."
        ),
        "timestamp": time.time(),
    })

    prompt = (
        f"OBJETIVO: {target.full_name or target.username or target.email}\n"
        f"Correo: {target.email or 'N/A'} · Alias: {target.username or 'N/A'} · "
        f"Universidad: {target.university or 'N/A'}\n"
        f"Contexto: {target.description or 'Ninguno'}\n\n"
        f"HALLAZGOS AMBIGUOS:\n"
        f"{json.dumps([_describe(e) for e in candidates], ensure_ascii=False, indent=1)}"
    )

    try:
        response = await litellm.acompletion(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            messages=[
                {"role": "system", "content": ARBITRATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        verdicts = _parse_verdicts(response.choices[0].message.content)
    except Exception as err:
        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "hybrid_arbitration_error",
            "layer": "refinement",
            "message": f"Arbitraje IA fallido ({err}). Los clusters se resuelven solo con el modelo.",
            "timestamp": time.time(),
        })
        return {"arbitration_candidates": len(candidates), "arbitration_failed": True}

    counts = {"match": 0, "no_match": 0, "uncertain": 0}
    for entity in candidates:
        result = verdicts.get(str(entity.id))
        if not result:
            continue

        verdict = result["verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
        previous = round(_attribution(entity), 3)
        applied = VERDICT_SCORES.get(verdict)

        entity.metadata_info = {
            **(entity.metadata_info or {}),
            "llm_arbitration": {
                "verdict": verdict,
                "rationale": result["rationale"],
                "model": settings.llm_model,
                "model_score": previous,
                # `applied_score` es lo único que el resolutor mira. Si el
                # veredicto es "uncertain" no hay puntuación efectiva y manda el
                # modelo, como si el arbitraje no hubiera existido.
                "applied_score": applied,
            },
        }

        if applied is not None:
            await event_bus.publish(investigation_id, {
                "type": "log",
                "phase": "hybrid_arbitration_verdict",
                "layer": "refinement",
                "message": (
                    f"Arbitraje IA · {entity.platform or entity.entity_type} "
                    f"{entity.value}: {verdict} ({previous:.2f} → {applied:.2f}). "
                    f"{result['rationale']}"
                ),
                "timestamp": time.time(),
            })

    return {
        "arbitration_candidates": len(candidates),
        "arbitration_answered": sum(counts.values()),
        "arbitration_match": counts["match"],
        "arbitration_no_match": counts["no_match"],
        "arbitration_uncertain": counts["uncertain"],
    }
