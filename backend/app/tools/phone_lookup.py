from typing import List
import phonenumbers
from phonenumbers import geocoder, carrier
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class PhoneLookupTool(BaseTool):
    name = "phone_lookup"
    description = (
        "Analiza números telefónicos para determinar país, región, operadora móvil "
        "y generar enlaces directos a servicios de mensajería (WhatsApp / Telegram)."
    )
    category = ToolCategory.PHONE
    required_inputs = ["phone"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if not context.phone or not context.phone.strip():
            return []

        raw_phone = context.phone.strip()
        findings: List[ToolFinding] = []

        try:
            # Default to Peru (PE) if no country code provided
            default_region = "PE"
            parsed = phonenumbers.parse(raw_phone, default_region)

            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
                region_name = geocoder.description_for_number(parsed, "es") or "Perú"
                carrier_name = carrier.name_for_number(parsed, "es") or "Operador móvil"
                clean_digits = "".join(filter(str.isdigit, e164))

                wa_url = f"https://wa.me/{clean_digits}"
                tg_url = f"https://t.me/+{clean_digits}"

                findings.append(
                    ToolFinding(
                        entity_type="phone",
                        platform="telephony",
                        value=e164,
                        display_name=f"{national} ({carrier_name})",
                        metadata_info={
                            "e164": e164,
                            "national": national,
                            "region": region_name,
                            "carrier": carrier_name,
                            "whatsapp_link": wa_url,
                            "telegram_link": tg_url,
                        },
                        confidence=0.95,
                        evidence_urls=[wa_url],
                    )
                )
        except Exception:
            # Record basic formatted phone
            findings.append(
                ToolFinding(
                    entity_type="phone",
                    platform="telephony",
                    value=raw_phone,
                    display_name=raw_phone,
                    metadata_info={"raw": raw_phone, "valid": False},
                    confidence=0.50,
                    evidence_urls=[],
                )
            )

        return findings
