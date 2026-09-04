import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.events import event_bus
from app.engine.persistence import build_relationships, persist_findings
from app.engine.pivot_rules import extract_and_apply_pivots
from app.models.entity import Entity
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry


@dataclass
class SweepResult:
    """
    Resultado de una barrida heurística, ANTES de persistir.

    `execute_investigation` la consume y persiste; el motor hibrido la consume
    para encadenar después su capa de refinamiento por IA y persistir una sola
    vez, de modo que la deduplicación vea los hallazgos de las dos capas juntos
    en lugar de crear entidades repetidas.
    """

    findings: List[ToolFinding] = field(default_factory=list)
    context: Optional[TargetContext] = None
    executed_runs: Set[str] = field(default_factory=set)
    rounds: int = 0


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

    async def collect_findings(
        self,
        investigation_id: str,
        target: Target,
    ) -> SweepResult:
        """
        Ejecuta la barrida heuristica completa y devuelve los hallazgos en bruto.

        Se separó de `execute_investigation` porque el motor hibrido necesita
        exactamente esta etapa -- las rondas con pivoteo determinista -- pero
        persistiendo después, junto con lo que añada su capa de refinamiento por
        IA. Si cada capa persistiera por su cuenta, la deduplicacion de
        `persist_findings` no vería los hallazgos de la otra y un mismo perfil
        descubierto por ambas acabaría como dos entidades.

        Todos los eventos que emite viajan con `layer: "heuristic"`, para que la
        consola pueda distinguir a simple vista qué capa produjo cada línea.
        """
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
                # Consentimiento para las fuentes que revelan a un tercero a
                # quién se investiga. Viaja en el contexto porque es la
                # herramienta la que decide si puede ejecutarse.
                "self_consent": bool((target.extra_data or {}).get("self_consent")),
            },
        )

        all_findings: List[ToolFinding] = []
        executed_runs: Set[str] = set()
        rounds_run = 0

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "init",
            "layer": "heuristic",
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

            rounds_run = round_idx

            await event_bus.publish(investigation_id, {
                "type": "log",
                "phase": f"round_{round_idx}",
                "layer": "heuristic",
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
                    "layer": "heuristic",
                    "message": (
                        f"Pivoteo heurístico activado: Descubiertos {len(context.all_emails())} correos, "
                        f"{len(context.all_usernames())} alias y {len(context.extra.get('candidate_urls', []))} enlaces candidatos."
                    ),
                    "timestamp": time.time(),
                })
            else:
                break

        return SweepResult(
            findings=all_findings,
            context=context,
            executed_runs=executed_runs,
            rounds=rounds_run,
        )

    async def execute_investigation(
        self,
        investigation_id: str,
        target: Target,
        db: AsyncSession,
    ) -> List[Entity]:
        start_time = time.time()

        sweep = await self.collect_findings(investigation_id, target)

        # Deduplicación, scoring y persistencia compartidos con el agente autónomo
        entities = await persist_findings(
            investigation_id=investigation_id,
            findings=sweep.findings,
            target=target,
            db=db,
            default_source_tool="osint_engine",
        )
        await build_relationships(investigation_id, entities, db)

        elapsed = round(time.time() - start_time, 2)
        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "complete",
            "layer": "heuristic",
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
            "layer": "heuristic",
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
                "layer": "heuristic",
                "findings_count": len(findings),
                "message": f"[{tool.name}] completado: {len(findings)} hallazgos.",
                "timestamp": time.time(),
            })
            return findings
        except Exception as err:
            await event_bus.publish(investigation_id, {
                "type": "tool_error",
                "tool": tool.name,
                "layer": "heuristic",
                "error": str(err),
                "message": f"[{tool.name}] error: {err}",
                "timestamp": time.time(),
            })
            return []


rule_engine = RuleEngine()
