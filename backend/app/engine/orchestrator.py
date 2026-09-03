import asyncio
import time
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.agent.agent import osint_agent
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.events import event_bus
from app.engine.rule_engine import rule_engine
from app.identity.resolver import identity_resolver
from app.identity.risk import calculate_risk_score
from app.models.investigation import Investigation


class Orchestrator:
    """Master Investigation Orchestrator."""

    async def run_investigation(self, investigation_id: UUID) -> None:
        """Background task entry point for running an investigation."""
        start_time = time.time()

        async with async_session_maker() as db:
            # 1. Load investigation and target
            stmt = (
                select(Investigation)
                .where(Investigation.id == investigation_id)
                .options(selectinload(Investigation.target))
            )
            result = await db.execute(stmt)
            investigation = result.scalar_one_or_none()
            if not investigation:
                return

            investigation.status = "running"
            await db.commit()

            str_id = str(investigation_id)
            target = investigation.target

            try:
                # 2. Execute OSINT extraction: Autonomous Agent vs Rule-Based
                use_agent = (
                    investigation.strategy == "agentic"
                    or (investigation.strategy == "auto" and settings.ai_enabled)
                )

                if use_agent and settings.ai_enabled:
                    from app.agent.autonomous_agent import autonomous_agent
                    entities = await autonomous_agent.run(str_id, target, db)
                else:
                    entities = await rule_engine.execute_investigation(str_id, target, db)

                # 3. Resolve Identity Clusters
                clusters = identity_resolver.resolve_clusters(investigation.id, entities, target)
                for cluster in clusters:
                    db.add(cluster)
                await db.flush()

                # 4. Calculate Risk & Exposure Score
                risk_score, risk_level, recommendations = calculate_risk_score(entities, target)
                investigation.risk_score = risk_score

                # 5. Generate Intelligence Narrative (AI or Template)
                narrative = await osint_agent.generate_intelligence_narrative(
                    target=target,
                    entities=entities,
                    risk_score=risk_score,
                    risk_level=risk_level,
                )
                investigation.summary = narrative

                # 6. Record Metrics for Academic Research
                elapsed = round(time.time() - start_time, 2)
                investigation.metrics = {
                    "execution_time_seconds": elapsed,
                    "entities_discovered": len(entities),
                    "clusters_formed": len(clusters),
                    "risk_level": risk_level,
                    "recommendations": recommendations,
                    "ai_enhanced": bool(settings.ai_enabled),
                    "strategy_used": investigation.strategy,
                }
                investigation.status = "completed"
                investigation.completed_at = datetime.now(timezone.utc)

                await db.commit()

                # 7. Broadcast completion event via SSE
                await event_bus.publish(str_id, {
                    "type": "investigation_complete",
                    "status": "completed",
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "entities_count": len(entities),
                    "elapsed_seconds": elapsed,
                    "message": "Investigación y mapa digital finalizados con éxito.",
                    "timestamp": time.time(),
                })

            except Exception as err:
                investigation.status = "failed"
                investigation.metrics = {"error": str(err), "time": time.time() - start_time}
                await db.commit()

                await event_bus.publish(str_id, {
                    "type": "investigation_error",
                    "status": "failed",
                    "error": str(err),
                    "message": f"Error durante la investigación: {err}",
                    "timestamp": time.time(),
                })


orchestrator = Orchestrator()
