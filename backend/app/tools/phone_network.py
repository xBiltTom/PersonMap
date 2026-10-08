"""Optional authenticated network lookup, disabled unless packages are configured."""

from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.tools import http_client

ALLOWED_FIELDS = {"line_type_intelligence", "line_status"}


async def lookup_phone_network(e164: str) -> dict:
    fields = list(dict.fromkeys(settings.phone_twilio_fields))
    if not fields:
        return {"status": "disabled"}
    if any(field not in ALLOWED_FIELDS for field in fields):
        return {"status": "configuration_error"}
    if not settings.phone_twilio_api_key or not settings.phone_twilio_api_secret:
        return {"status": "not_configured"}
    endpoint = "https://lookups.twilio.com/v2/PhoneNumbers/" + quote(e164, safe="")
    observation = {"provider": "twilio", "source_url": endpoint, "fields": fields,
                   "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        # No automatic redirects or retries for credentialed, potentially billed requests.
        async with http_client.build_client(timeout=8, public_only=True, follow_redirects=False, max_retries=0) as client:
            response = await client.get(endpoint, params={"Fields": ",".join(fields)},
                                        auth=httpx.BasicAuth(settings.phone_twilio_api_key,
                                                            settings.phone_twilio_api_secret.get_secret_value()))
        if response.status_code != 200:
            return {**observation, "status": "error", "http_status": response.status_code}
        data = response.json()
        if not isinstance(data, dict) or data.get("phone_number") != e164:
            return {**observation, "status": "error", "reason": "mismatched_phone_or_schema"}
        packages = {}
        for field in fields:
            value = data.get(field)
            if not isinstance(value, dict):
                packages[field] = {"status": "unknown"}
            elif value.get("error_code") is not None:
                packages[field] = {"status": "unsupported" if value["error_code"] == 60601 else "error", "error_code": value["error_code"]}
            elif field == "line_type_intelligence":
                packages[field] = {"status": "reported", "carrier_name": value.get("carrier_name"),
                                   "line_type": value.get("type"), "mcc": value.get("mobile_country_code"),
                                   "mnc": value.get("mobile_network_code")}
            else:
                status = value.get("status")
                packages[field] = {"status": "reported" if status in {"Active", "Inactive", "Reachable", "Unreachable", "Unknown"} else "unknown", "line_status": status}
        return {**observation, "status": "completed", "packages": packages}
    except (httpx.HTTPError, ValueError):
        return {**observation, "status": "error", "reason": "request_or_response_error"}
