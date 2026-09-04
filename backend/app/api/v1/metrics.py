from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.investigation import Investigation

router = APIRouter()

# Umbral por encima del cual el resolutor atribuye un hallazgo al objetivo.
CONFIRMED_THRESHOLD = 0.70


# Etiquetas de los tres brazos experimentales, en el orden en que se presentan.
ENGINES = ("rules", "agentic", "hybrid")

ENGINE_LABELS = {
    "rules": "Motor por Reglas",
    "agentic": "Agente IA Autónomo",
    "hybrid": "Híbrido (Reglas + IA)",
}


def engine_of(investigation: Investigation) -> str:
    """
    Motor que REALMENTE ejecutó la investigación.

    Agrupar por `strategy` era incorrecto y sesgaba la comparativa: `auto` se
    contaba como agéntico aunque el orquestador hubiera caído al motor de reglas
    por no haber LLM configurado, y una `hybrid` sin LLM es una corrida de reglas
    con otro nombre. Desde la Fase 3 el orquestador anota `engine_used` en las
    métricas; para los expedientes anteriores se reconstruye a partir de
    `ai_enhanced`, que ya registraba si había LLM en el momento de ejecutar.
    """
    metrics = investigation.metrics or {}
    recorded = metrics.get("engine_used")
    if recorded in ENGINES:
        return recorded

    strategy = investigation.strategy
    if strategy == "rule_based":
        return "rules"
    if strategy == "hybrid":
        return "hybrid" if metrics.get("ai_enhanced") else "rules"
    if strategy in ("agentic", "auto"):
        return "agentic" if metrics.get("ai_enhanced") else "rules"
    return "rules"


def _score_distribution(investigations: List[Investigation]) -> Dict[str, Any]:
    """
    Histograma de las probabilidades de atribución en deciles.

    Es la evidencia de que el modelo discrimina. Antes de la reescritura del
    scorer la distribución era trimodal ({0.05, 0.45, 0.95}) porque las señales
    sin dato se contaban como desacuerdo y unos atajos aplastaban lo
    intermedio; un histograma plano o concentrado en pocos valores delata esa
    patología de un vistazo.
    """
    scores: List[float] = []
    versions: Dict[str, int] = {}

    for inv in investigations:
        for entity in inv.entities:
            if entity.identity_score is None:
                continue
            scores.append(float(entity.identity_score))
            version = entity.scorer_version or "sin versión"
            versions[version] = versions.get(version, 0) + 1

    buckets = [0] * 10
    for score in scores:
        index = min(9, max(0, int(score * 10)))
        buckets[index] += 1

    total = len(scores)
    attributed = sum(1 for s in scores if s >= CONFIRMED_THRESHOLD)

    return {
        "total_scored_entities": total,
        "buckets": [
            {"from": round(i / 10, 1), "to": round((i + 1) / 10, 1), "count": count}
            for i, count in enumerate(buckets)
        ],
        "attributed_count": attributed,
        "attributed_pct": round(attributed / total * 100, 1) if total else 0.0,
        "distinct_values": len({round(s, 3) for s in scores}),
        # Las puntuaciones solo son comparables entre sí dentro de una misma
        # versión del modelo; mezclarlas en un agregado invalidaría el análisis.
        "scorer_versions": versions,
    }


@router.get("/investigations/metrics/comparison")
async def get_scientific_comparison(db: AsyncSession = Depends(get_db)):
    """
    Computes comparative metrics between Rule-Based OSINT and Agentic (AI) OSINT
    for the university scientific research paper.
    Outputs metrics and ready-to-use LaTeX table snippet.
    """
    stmt = (
        select(Investigation)
        .where(Investigation.status == "completed")
        .options(selectinload(Investigation.entities), selectinload(Investigation.identity_clusters))
    )
    result = await db.execute(stmt)
    investigations = result.scalars().all()

    grouped: Dict[str, List[Investigation]] = {engine: [] for engine in ENGINES}
    for inv in investigations:
        grouped[engine_of(inv)].append(inv)

    def summarize_group(invs: List[Investigation]) -> Dict[str, Any]:
        if not invs:
            return {
                "count": 0,
                "avg_execution_time": 0.0,
                "avg_entities": 0.0,
                "avg_clusters": 0.0,
                "avg_risk_score": 0.0,
            }

        total_time = sum(
            (inv.metrics or {}).get("execution_time_seconds", 0.0) for inv in invs
        )
        total_entities = sum(len(inv.entities) for inv in invs)
        total_clusters = sum(len(inv.identity_clusters) for inv in invs)
        total_score = sum(inv.risk_score for inv in invs)
        n = len(invs)

        return {
            "count": n,
            "avg_execution_time": round(total_time / n, 2),
            "avg_entities": round(total_entities / n, 1),
            "avg_clusters": round(total_clusters / n, 1),
            "avg_risk_score": round(total_score / n, 1),
        }

    stats = {engine: summarize_group(invs) for engine, invs in grouped.items()}

    # Aportación específica del híbrido: cuántas entidades existen solo gracias a
    # la capa de refinamiento por IA. Es la cifra que justifica (o desmonta) la
    # tercera condición; sin ella, "el híbrido encuentra más" no es demostrable.
    hybrid_invs = grouped["hybrid"]
    hybrid_contribution = {
        "investigations": len(hybrid_invs),
        "avg_heuristic_findings": 0.0,
        "avg_refinement_findings": 0.0,
        "avg_entities_only_from_llm": 0.0,
        "refinement_calls_skipped": 0,
        "arbitration_used": 0,
    }
    if hybrid_invs:
        n = len(hybrid_invs)
        metrics_list = [inv.metrics or {} for inv in hybrid_invs]
        hybrid_contribution.update({
            "avg_heuristic_findings": round(
                sum(m.get("hybrid_heuristic_findings", 0) for m in metrics_list) / n, 1
            ),
            "avg_refinement_findings": round(
                sum(m.get("hybrid_refinement_findings", 0) for m in metrics_list) / n, 1
            ),
            "avg_entities_only_from_llm": round(
                sum(m.get("hybrid_entities_only_from_llm", 0) for m in metrics_list) / n, 1
            ),
            "refinement_calls_skipped": sum(
                m.get("hybrid_refinement_calls_skipped", 0) for m in metrics_list
            ),
            "arbitration_used": sum(
                1 for m in metrics_list if m.get("arbitration_answered")
            ),
        })

    def row(title: str, key: str, suffix: str = "") -> str:
        cells = " & ".join(f"{stats[e][key]}{suffix}" for e in ENGINES)
        return rf"{title} & {cells} \\ \hline"

    latex_table = rf"""\begin{{table}}[h]
\centering
\caption{{Comparación Experimental: OSINT por Reglas vs. Agéntico con IA vs. Híbrido}}
\label{{tab:osint_comparison}}
\begin{{tabular}}{{|l|c|c|c|}}
\hline
\textbf{{Métrica de Evaluación}} & \textbf{{Motor por Reglas}} & \textbf{{Agente IA Autónomo}} & \textbf{{Híbrido (Reglas + IA)}} \\ \hline
{row("Muestras analizadas", "count")}
{row("Tiempo medio de ejecución (s)", "avg_execution_time", "s")}
{row("Entidades descubiertas (media)", "avg_entities")}
{row("Clusters de identidad resueltos", "avg_clusters")}
{row("Score de Exposición Medio", "avg_risk_score", "/100")}
\end{{tabular}}
\end{{table}}"""

    return {
        "summary": {
            "total_investigations": len(investigations),
            # Se conservan los nombres de clave anteriores para no romper los
            # clientes ya escritos, y se añade el tercer brazo.
            "rule_based": stats["rules"],
            "agentic": stats["agentic"],
            "hybrid": stats["hybrid"],
        },
        "engine_labels": ENGINE_LABELS,
        "hybrid_contribution": hybrid_contribution,
        "identity_score_distribution": _score_distribution(investigations),
        "latex_table": latex_table,
        "investigations_sample": [
            {
                "id": str(inv.id),
                "strategy": inv.strategy,
                "engine_used": engine_of(inv),
                "execution_time": (inv.metrics or {}).get("execution_time_seconds", 0),
                "entities_count": len(inv.entities),
                "risk_score": inv.risk_score,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in investigations[:20]
        ],
    }
