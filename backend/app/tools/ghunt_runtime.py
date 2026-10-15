"""GHunt's isolated runtime, input policy and non-secret capability metadata."""
import hashlib
import base64
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.core.config import settings
from app.tools.maigret_ids import identifier_values

GHUNT_VERSION = "2.3.4"
ROOT = Path(__file__).resolve().parents[2]
SERVICES = {"maps", "calendar", "play_games"}


def python_path():
    return Path(settings.ghunt_python or ROOT / "integrations/ghunt/.venv/bin/python").absolute()


def credentials_path():
    return Path(settings.ghunt_credentials_file).expanduser().absolute() if settings.ghunt_credentials_file else None


def capabilities():
    python = python_path()
    creds = credentials_path()
    installed = python.is_file() and any((python.parent.parent / "lib").glob("python*/site-packages/ghunt-2.3.4.dist-info/METADATA"))
    status = ("disabled" if not settings.ghunt_enabled else
              "runtime_missing" if not installed else
              "session_not_configured" if creds is None else
              "session_missing" if not creds.is_file() else "configured")
    return {"version": GHUNT_VERSION, "adapter_version": 3, "status": status,
            "runtime_available": installed, "session_configured": creds is not None,
            "session_available": creds.is_file() if creds else False,
            "session_validated": False, "requires_operator_session": True,
            "inputs": ["email", "gaia_id", "public_drive_url"],
            "services": sorted(SERVICES.intersection(settings.ghunt_services)),
            "maps_scope": "contribution_statistics", "max_queries": settings.ghunt_max_queries,
            "max_drive_files": settings.ghunt_max_drive_files, "max_events": settings.ghunt_max_events,
            "max_requests": settings.ghunt_max_requests, "worker_timeout": settings.ghunt_worker_timeout,
            "request_timeout": settings.ghunt_request_timeout,
            "ownership_scope": "candidate_not_identity_confirmation"}


def config_fingerprint():
    # Paths/credentials never leave the administrator's configuration. The
    # opaque hash partitions caches after credential replacement/rotation.
    creds = credentials_path()
    signature = "unconfigured"
    if creds:
        try:
            with creds.open("rb") as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Session too large")
            data = json.loads(base64.b64decode(raw, validate=True))
            # Cookies/OAuth access tokens rotate during normal use. Only the
            # durable operator identity token partitions collection coverage.
            token = data.get("android", {}).get("master_token") or raw.hex()
            signature = hashlib.sha256((str(creds) + ":" + token).encode()).hexdigest()
        except (OSError, ValueError, TypeError, AttributeError):
            signature = "unavailable"
    return {**capabilities(), "session_revision": signature}


def config_id():
    return hashlib.sha256(json.dumps(config_fingerprint(), sort_keys=True).encode()).hexdigest()


def drive_resource(raw):
    """Accept explicit public Drive/Docs routes, never arbitrary fetch URLs."""
    try:
        parts = urlsplit(raw)
        if (parts.scheme != "https" or parts.hostname not in {"drive.google.com", "docs.google.com"}
                or parts.username or parts.password or parts.port not in {None, 443}):
            return None
        found = re.fullmatch(r"/(?:file/d|drive/(?:u/[0-9]+/)?folders|(?:document|spreadsheets|presentation|forms)/d)/([A-Za-z0-9_-]{10,200})(?:/(?:view|edit|preview))?/?", parts.path)
        if found:
            identifier = found[1]
        elif parts.path in {"/open", "/uc"} and parts.hostname == "drive.google.com":
            identifier = parse_qs(parts.query).get("id", [""])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", identifier):
                return None
        else:
            return None
        key = parse_qs(parts.query).get("resourcekey", [""])[0]
        if key and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", key):
            return None
        return {"id": identifier, "resource_key": key, "url": f"https://drive.google.com/file/d/{identifier}/view"}
    except (ValueError, TypeError):
        return None


def queries(context):
    selection = context.extra.get("ghunt_selection")
    emails = ([selection["email"]] if selection.get("email") else []) if selection is not None else context.all_emails()
    identifiers = selection.get("identifiers", []) if selection is not None else context.extra.get("maigret_identifiers", [])
    urls = selection.get("candidate_urls", []) if selection is not None else context.extra.get("candidate_urls", [])
    result = [{"kind": "email", "value": email} for email in emails
              if re.fullmatch(r"[^\s@<>\x00-\x1f]{1,64}@[^\s@<>\x00-\x1f]{1,253}\.[^\s@<>\x00-\x1f]+", email) and len(email) <= 320]
    result.extend({"kind": "gaia", "value": item["value"]}
                  for item in identifier_values(identifiers)
                  if item["id_type"] == "gaia_id" and re.fullmatch(r"[0-9]{10,30}", item["value"]))
    resources = [drive_resource(url) for url in urls]
    result.extend({"kind": "drive", "value": item["id"], "resource_key": item["resource_key"]}
                  for item in resources if item)
    return list({query_key(item): item for item in result}.values())


def select_call_inputs(context, inputs):
    """Explicit MCP/agent selections stay isolated from accumulated pivots."""
    from app.schemas.workspace import ToolInputs
    context.extra.pop("ghunt_selection", None)
    supplied = {key: inputs[key] for key in ("email", "identifiers", "candidate_urls") if inputs.get(key)}
    if supplied:
        validated = ToolInputs.model_validate(supplied)
        context.extra["ghunt_selection"] = validated.model_dump(include={"email", "identifiers", "candidate_urls"}, exclude_none=True)


def query_key(query):
    # Resource keys can grant link access; never persist them in diagnostics.
    return query["kind"] + ":" + query["value"]


def execution_summary(context):
    """Small trace/console projection; no session paths, tokens or query values."""
    diagnostics = context.extra.get("ghunt_diagnostics", {})
    items = [item for key, item in diagnostics.items() if key != "runtime"]
    return {"runtime": diagnostics.get("runtime", {}),
            "statuses": sorted({item["status"] for item in items}),
            "queries": len(items), "requests": sum(item.get("requests", 0) for item in items),
            "services": [item.get("services", {}) for item in items]}
