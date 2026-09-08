"""
Segunda pasada de puntuación: señales caras que no caben en el camino síncrono.

El scorer se ejecuta durante la persistencia, es síncrono y debe ser rápido:
solo mira texto ya presente en los metadatos. Pero dos de las señales más
valiosas necesitan red — descargar y hashear avatares, y pedir embeddings a un
proveedor de LLM — y son asíncronas por naturaleza.

Resolverlo moviendo la llamada al scorer más tarde en el pipeline habría
obligado a convertirlo en corutina, cambio que se propaga a los dos motores y
rompe sus tests. En su lugar el scoring queda en dos pasadas:

  1. Síncrona, durante `persist_findings`: señales textuales.
  2. Asíncrona y en lote, aquí: se calculan `avatar_similarity` y
     `semantic_similarity`, se escriben en los metadatos y **se re-puntúan solo
     las entidades afectadas**.

Ambas señales están declaradas en `scorer.SIGNALS` como evaluables únicamente si
su clave está presente en los metadatos, así que una entidad que no pase por
aquí no queda penalizada: simplemente se puntúa con menos señales.
"""

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.identity.avatar_hasher import avatar_hasher
from app.identity.avatar_harvest import harvest_avatar_urls
from app.identity.scorer import compute_identity_score
from app.models.entity import Entity
from app.models.target import Target

# Distancia de Hamming máxima para considerar dos avatares "el mismo". El
# umbral de 6 del hasher es permisivo para una señal que empuja tanto; aquí se
# aprieta, porque un falso positivo agrupa a dos personas distintas bajo una
# misma identidad.
AVATAR_MAX_DISTANCE = 4
AVATAR_HASH_BITS = 8


async def enrich_and_rescore(
    entities: List[Entity],
    target: Target,
) -> Dict[str, Any]:
    """
    Calcula las señales caras y re-puntúa lo que cambie.

    Devuelve un resumen para las métricas de la investigación. No hace commit:
    la transacción la cierra el orquestador.
    """
    summary: Dict[str, Any] = {
        "avatar_correlations": 0,
        "avatars_harvested": 0,
        "semantic_comparisons": 0,
        "rescored_entities": 0,
    }
    if not entities:
        return summary

    touched: Dict[str, Entity] = {}

    # Cosecha ACTIVA: antes de comparar, se construyen las URLs de avatar de las
    # cuentas ya confirmadas en los proveedores con patrón conocido. Hasta ahora
    # solo se comparaban los avatares que alguna herramienta hubiera expuesto por
    # casualidad en sus metadatos, que eran muy pocos.
    summary["avatars_harvested"] = await harvest_avatar_urls(entities)

    avatar_pairs = await _apply_avatar_similarity(entities, touched)
    summary["avatar_correlations"] = avatar_pairs

    semantic = await _apply_semantic_similarity(entities, target, touched)
    summary["semantic_comparisons"] = semantic

    for entity in touched.values():
        score, breakdown = compute_identity_score(
            display_name=entity.display_name,
            value=entity.value,
            metadata=entity.metadata_info or {},
            target=target,
        )
        entity.identity_score = score
        entity.scorer_version = breakdown.get("scorer_version")
        entity.confidence = round(max(float(entity.existence_confidence or 0.0), score), 3)
        entity.metadata_info = {
            **(entity.metadata_info or {}),
            "identity_breakdown": breakdown,
            "identity_score": score,
        }

    summary["rescored_entities"] = len(touched)
    return summary


# --- Avatares -------------------------------------------------------------


async def _apply_avatar_similarity(
    entities: List[Entity], touched: Dict[str, Entity]
) -> int:
    """
    Traduce las correlaciones perceptuales a un grado de acuerdo [0,1].

    Antes el resultado del hasher se aplicaba como `confidence = max(conf, 0.99)`,
    un atajo que saltaba por encima del modelo: dos avatares por defecto
    idénticos —la silueta genérica que sirve Gravatar, por ejemplo— bastaban
    para declarar "identidad confirmada" a dos personas sin ninguna relación.
    Ahora entra como una señal más, que el Fellegi-Sunter pondera junto al resto.
    """
    try:
        correlations = await avatar_hasher.correlate_entity_avatars(entities)
    except Exception:
        return 0

    by_id = {str(e.id): e for e in entities}
    best: Dict[str, int] = {}

    for corr in correlations:
        distance = int(corr.get("hamming_distance", AVATAR_HASH_BITS**2))
        if distance > AVATAR_MAX_DISTANCE:
            continue
        for key in ("entity_a_id", "entity_b_id"):
            ent_id = corr.get(key)
            if ent_id in by_id:
                best[ent_id] = min(best.get(ent_id, distance), distance)

    for ent_id, distance in best.items():
        entity = by_id[ent_id]
        # Acuerdo decreciente con la distancia: 0 bits de diferencia es acuerdo
        # pleno; en el límite tolerado baja a 0.5.
        similarity = round(max(0.0, 1.0 - distance / (2 * AVATAR_MAX_DISTANCE)), 2)
        entity.metadata_info = {
            **(entity.metadata_info or {}),
            "avatar_similarity": similarity,
            "avatar_hamming_distance": distance,
        }
        touched[ent_id] = entity

    return len(best)


# --- Semántica ------------------------------------------------------------


async def _apply_semantic_similarity(
    entities: List[Entity], target: Target, touched: Dict[str, Entity]
) -> int:
    """
    Compara la biografía de cada perfil con el contexto conocido del objetivo.

    Capta equivalencias que el cotejo léxico no ve: "UNMSM" y "Universidad
    Nacional Mayor de San Marcos" tienen distancia de edición enorme y describen
    lo mismo. Desactivado si no hay modelo de embeddings configurado, igual que
    el resto de la capa de IA.
    """
    if not settings.semantic_matching_enabled:
        return 0

    reference = _target_reference_text(target)
    if not reference:
        return 0

    candidates: List[Tuple[Entity, str]] = []
    for entity in entities:
        bio = _entity_bio(entity)
        if bio:
            candidates.append((entity, bio))
    if not candidates:
        return 0

    # Una sola llamada en lote para todo: un `await` por entidad dentro de un
    # bucle multiplicaría la latencia y el coste de la investigación.
    vectors = await _embed([reference] + [bio for _, bio in candidates])
    if not vectors or len(vectors) != len(candidates) + 1:
        return 0

    reference_vec = vectors[0]
    for (entity, _), vector in zip(candidates, vectors[1:]):
        similarity = _cosine(reference_vec, vector)
        # Por debajo de 0.5 la similitud es ruido: cualquier par de textos en el
        # mismo idioma y dominio comparte una base semántica considerable.
        gamma = round(max(0.0, (similarity - 0.5) * 2.0), 2)
        entity.metadata_info = {
            **(entity.metadata_info or {}),
            "semantic_similarity": gamma,
            "semantic_cosine": round(similarity, 3),
        }
        touched[str(entity.id)] = entity

    return len(candidates)


def _target_reference_text(target: Target) -> str:
    parts = [target.full_name, target.university, target.description]
    return " ".join(p.strip() for p in parts if p and p.strip())


def _entity_bio(entity: Entity) -> str:
    meta = entity.metadata_info or {}
    parts = [meta.get("bio"), meta.get("snippet"), meta.get("og_description")]
    text = " ".join(str(p).strip() for p in parts if isinstance(p, str) and p.strip())
    # Textos muy cortos no aportan señal semántica y gastan tokens.
    return text if len(text) >= 25 else ""


async def _embed(texts: Sequence[str]) -> Optional[List[List[float]]]:
    try:
        import litellm

        response = await litellm.aembedding(
            model=settings.llm_embedding_model,
            input=list(texts),
            api_key=settings.llm_api_key,
        )
        return [item["embedding"] for item in response["data"]]
    except Exception:
        # La señal semántica es opcional por diseño: si el proveedor falla, la
        # investigación continúa con el resto de señales.
        return None


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
