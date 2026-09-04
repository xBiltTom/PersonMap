import asyncio
import time
from typing import List, Set
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.events import event_bus
from app.engine.pivot_rules import extract_and_apply_pivots
from app.identity.scorer import compute_identity_score
from app.models.entity import Entity
from app.models.relationship import Relationship
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry


class RuleEngine:
    """
    Intelligent code-based orchestrator.
    Runs multiple tool rounds with automated heuristic pivoting.
    """

    MAX_ROUNDS = 4

    def _get_tool_run_key(self, tool, context: TargetContext) -> str:
        parts = [tool.name]
        for req in getattr(tool, "required_inputs", []):
            if req == "username":
                parts.append("u:" + ",".join(sorted(context.all_usernames())))
            elif req == "email":
                parts.append("e:" + ",".join(sorted(context.all_emails())))
            elif req == "phone":
                parts.append(f"p:{context.phone or ''}")
            elif req == "dni":
                parts.append(f"d:{context.dni or ''}")
            elif req == "full_name":
                parts.append(f"n:{context.full_name or ''}")
            elif req == "candidate_urls":
                urls = context.extra.get("candidate_urls", [])
                parts.append("urls:" + ",".join(sorted(str(u) for u in urls)))
            else:
                val = getattr(context, req, None) or context.extra.get(req, "")
                parts.append(f"{req}:{val}")
        return "|".join(parts)

    async def execute_investigation(
        self,
        investigation_id: str,
        target: Target,
        db: AsyncSession,
    ) -> List[Entity]:
        start_time = time.time()
        context = TargetContext(
            full_name=target.full_name,
            email=target.email,
            username=target.username,
            phone=target.phone,
            dni=target.dni,
            university=target.university,
            description=target.description,
            extra={
                "candidate_urls": [],
                "avatar_urls": [],
                "investigation_id": investigation_id,
            },
        )

        all_findings: List[ToolFinding] = []
        executed_runs: Set[str] = set()

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "init",
            "message": f"Iniciando orquestador OSINT para el objetivo: {target.full_name or target.username or target.email}",
            "timestamp": time.time(),
        })

        for round_idx in range(1, self.MAX_ROUNDS + 1):
            runnable = [
                tool for tool in tool_registry.get_all()
                if tool.can_run(context) and self._get_tool_run_key(tool, context) not in executed_runs
            ]
            if not runnable:
                break

            await event_bus.publish(investigation_id, {
                "type": "log",
                "phase": f"round_{round_idx}",
                "message": f"Ronda {round_idx}: Despachando {len(runnable)} módulos OSINT ({', '.join(t.name for t in runnable)})",
                "timestamp": time.time(),
            })

            tasks = []
            for tool in runnable:
                executed_runs.add(self._get_tool_run_key(tool, context))
                tasks.append(self._run_single_tool(investigation_id, tool, context))

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            round_findings: List[ToolFinding] = []

            for res in batch_results:
                if isinstance(res, list):
                    round_findings.extend(res)

            all_findings.extend(round_findings)

            # Heuristic Pivot Analysis
            has_pivots = extract_and_apply_pivots(round_findings, context)
            if has_pivots:
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "pivot",
                    "message": (
                        f"Pivoteo heurístico activado: Descubiertos {len(context.all_emails())} correos, "
                        f"{len(context.all_usernames())} alias y {len(context.extra.get('candidate_urls', []))} enlaces candidatos."
                    ),
                    "timestamp": time.time(),
                })
            else:
                break

        # Deduplicate findings by (entity_type, platform, normalized value), preserving highest confidence
        deduped_findings: dict[tuple[str, str, str], ToolFinding] = {}
        for f in all_findings:
            key = (
                f.entity_type,
                (f.platform or "").lower(),
                f.value.strip().rstrip("/").lower(),
            )
            if key not in deduped_findings or f.confidence > deduped_findings[key].confidence:
                deduped_findings[key] = f

        # Persist entities and compute identity resolution scores
        entities: List[Entity] = []
        for f in deduped_findings.values():
            score, breakdown = compute_identity_score(
                display_name=f.display_name,
                value=f.value,
                metadata=f.metadata_info,
                target=target,
            )
            # Combine tool baseline with score
            final_conf = round(max(f.confidence, score), 2)

            entity = Entity(
                investigation_id=investigation_id,
                entity_type=f.entity_type,
                platform=f.platform,
                value=f.value,
                display_name=f.display_name or f.value,
                metadata_info=f.metadata_info,
                confidence=final_conf,
                verified=False,
                source_tool=f.metadata_info.get("source_tool", "osint_engine"),
            )
            db.add(entity)
            entities.append(entity)

        await db.flush()

        # Build relationships between entities (graph edges)
        for i, ent_a in enumerate(entities):
            for ent_b in entities[i + 1 :]:
                rel_type, strength = self._detect_relationship(ent_a, ent_b)
                if rel_type:
                    rel = Relationship(
                        investigation_id=investigation_id,
                        source_entity_id=ent_a.id,
                        target_entity_id=ent_b.id,
                        relation_type=rel_type,
                        strength=strength,
                    )
                    db.add(rel)

        await db.flush()

        elapsed = round(time.time() - start_time, 2)
        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "complete",
            "message": f"Fase de extracción finalizada: {len(entities)} entidades públicas registradas en {elapsed}s",
            "timestamp": time.time(),
        })

        return entities

    async def _run_single_tool(
        self,
        investigation_id: str,
        tool,
        context: TargetContext,
    ) -> List[ToolFinding]:
        await event_bus.publish(investigation_id, {
            "type": "tool_start",
            "tool": tool.name,
            "message": f"Ejecutando [{tool.name}]: {tool.description[:60]}...",
            "timestamp": time.time(),
        })

        try:
            findings = await tool.execute(context)
            # Tag source tool
            for f in findings:
                f.metadata_info["source_tool"] = tool.name

            await event_bus.publish(investigation_id, {
                "type": "tool_complete",
                "tool": tool.name,
                "findings_count": len(findings),
                "message": f"[{tool.name}] completado: {len(findings)} hallazgos.",
                "timestamp": time.time(),
            })
            return findings
        except Exception as err:
            await event_bus.publish(investigation_id, {
                "type": "tool_error",
                "tool": tool.name,
                "error": str(err),
                "message": f"[{tool.name}] error: {err}",
                "timestamp": time.time(),
            })
            return []

    def _detect_relationship(self, a: Entity, b: Entity) -> tuple[str | None, float]:
        # Same platform or shared username
        user_a = a.metadata_info.get("username", "").lower()
        user_b = b.metadata_info.get("username", "").lower()
        if user_a and user_b and user_a == user_b:
            return "same_username", 0.85

        # Email linkage
        if a.entity_type == "email" and b.metadata_info.get("emails"):
            if a.value.lower() in [e.lower() for e in b.metadata_info["emails"]]:
                return "uses_email", 0.95

        # Cross link
        links_a = a.metadata_info.get("linked_profiles", [])
        if any(b.value in l for l in links_a):
            return "linked_to", 0.90

        # General correlation by common domain / context
        if a.platform == b.platform:
            return "same_platform", 0.50

        return None, 0.0


rule_engine = RuleEngine()
