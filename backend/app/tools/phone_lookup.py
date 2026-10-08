from typing import List
import time
from app.core.events import event_bus

from app.core.config import settings
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.phone_network import lookup_phone_network
from app.tools.phone_numbers import analyze_phone, phone_identity


class PhoneLookupTool(BaseTool):
    name = "phone_lookup"
    description = "Analiza formato, país, tipo de línea y operador original; no confirma actividad ni titularidad"
    category = ToolCategory.PHONE
    required_inputs = ["phone"]

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.all_phones())

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings = []
        outcomes = context.extra.setdefault("phone_lookup_results", {})
        for identity in context.all_phones()[:settings.phone_max_numbers]:
            raw = context.phone if context.phone and (phone_identity(context.phone) or context.phone.strip()) == identity else identity
            facts = analyze_phone(raw)
            if identity in outcomes:
                continue
            if len(outcomes) >= settings.phone_max_numbers:
                break
            outcomes[identity] = facts
            if not facts["valid"]:
                investigation_id = context.extra.get("investigation_id")
                if investigation_id:
                    await event_bus.publish(investigation_id, {
                        "type": "log", "phase": "phone_validation", "tool": self.name,
                        "message": f"[{self.name}] Número no válido según el plan de numeración: {facts['validation_reason']}",
                        "timestamp": time.time(),
                    })
                continue
            network = await lookup_phone_network(facts["e164"]) if not facts.get("extension") else {"status": "unsupported_extension"}
            metadata = {"network_lookup": network, **facts, "source_tool": self.name, "verification_status": "numbering_plan_valid"}
            # These are generated shortcuts, not evidence that an account exists.
            if not facts.get("extension") and facts["line_type"] in {"mobile", "fixed_or_mobile", "fixed_line"}:
                digits = facts["e164"].lstrip('+')
                metadata.update(whatsapp_link=f"https://wa.me/{digits}", telegram_link=f"https://t.me/+{digits}",
                                contact_links_origin="derived", messaging_registration_status="unknown")
            evidence = context.extra.get("phone_observations", {}).get(identity, [])
            metadata["phone_observations"] = evidence
            findings.append(ToolFinding(entity_type="phone", platform="telephony", value=identity,
                                        display_name=facts["national"], metadata_info=metadata, confidence=0.5,
                                        evidence_urls=list(dict.fromkeys(item["source_url"] for item in evidence if item.get("source_url")))))
        return findings
