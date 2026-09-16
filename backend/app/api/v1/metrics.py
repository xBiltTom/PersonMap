from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.investigation import Investigation

router = APIRouter()

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
        .options(selectinload(Investigation.entities), selectinload(Investigation.correlation_groups))
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
            }

        total_time = sum(
            (inv.metrics or {}).get("execution_time_seconds", 0.0) for inv in invs
        )
        total_entities = sum(len(inv.entities) for inv in invs)
        total_clusters = sum(len(inv.correlation_groups) for inv in invs)
        n = len(invs)

        return {
            "count": n,
            "avg_execution_time": round(total_time / n, 2),
            "avg_entities": round(total_entities / n, 1),
            "avg_clusters": round(total_clusters / n, 1),
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
{row("Grupos de correlación", "avg_clusters")}
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
        "latex_table": latex_table,
        "investigations_sample": [
            {
                "id": str(inv.id),
                "strategy": inv.strategy,
                "engine_used": engine_of(inv),
                "execution_time": (inv.metrics or {}).get("execution_time_seconds", 0),
                "entities_count": len(inv.entities),
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in investigations[:20]
        ],
    }
