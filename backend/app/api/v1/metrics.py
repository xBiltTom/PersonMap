from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.investigation import Investigation

router = APIRouter()


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

    rule_based_list = [inv for inv in investigations if inv.strategy == "rule_based"]
    agentic_list = [inv for inv in investigations if inv.strategy in ["agentic", "auto"]]

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

    stats_rule = summarize_group(rule_based_list)
    stats_agent = summarize_group(agentic_list)

    # Generate LaTeX Table snippet for Overleaf / Academic Paper
    latex_table = f"""\\begin{{table}}[h]
\\centering
\\caption{{Comparación Experimental: OSINT Basado en Reglas vs. OSINT Agéntico con IA}}
\\label{{tab:osint_comparison}}
\\begin{{tabular}}{{|l|c|c|}}
\\hline
\\textbf{{Métrica de Evaluación}} & \\textbf{{Motor por Reglas}} & \\textbf{{Agente IA Autónomo}} \\\\ \\hline
Muestras analizadas & {stats_rule['count']} & {stats_agent['count']} \\\\ \\hline
Tiempo medio de ejecución (s) & {stats_rule['avg_execution_time']}s & {stats_agent['avg_execution_time']}s \\\\ \\hline
Entidades descubiertas (media) & {stats_rule['avg_entities']} & {stats_agent['avg_entities']} \\\\ \\hline
Clusters de identidad resueltos & {stats_rule['avg_clusters']} & {stats_agent['avg_clusters']} \\\\ \\hline
Score de Exposición Medio & {stats_rule['avg_risk_score']}/100 & {stats_agent['avg_risk_score']}/100 \\\\ \\hline
\\end{{tabular}}
\\end{{table}}"""

    return {
        "summary": {
            "total_investigations": len(investigations),
            "rule_based": stats_rule,
            "agentic": stats_agent,
        },
        "latex_table": latex_table,
        "investigations_sample": [
            {
                "id": str(inv.id),
                "strategy": inv.strategy,
                "execution_time": (inv.metrics or {}).get("execution_time_seconds", 0),
                "entities_count": len(inv.entities),
                "risk_score": inv.risk_score,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in investigations[:20]
        ],
    }
