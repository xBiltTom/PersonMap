"""GHunt adapter: native Google observations with explicit candidate provenance."""
import asyncio
import re
from urllib.parse import quote

from app.core.config import settings
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dni_public import public_source_url
from app.tools.ghunt_runner import run_ghunt
from app.tools.ghunt_runtime import capabilities, config_id, queries, query_key


def safe_url(raw):
    return public_source_url(raw) if isinstance(raw, str) else None


class GHuntTool(BaseTool):
    name = "ghunt"
    description = ("Consulta GHunt por correo, GAIA ID o URL explícita de Drive público. Requiere sesión del operador; "
                   "recupera perfil Google, estadísticas de Maps, Calendar público y candidatos de Play Games. "
                   "No confirma que los perfiles pertenezcan al objetivo ni sigue colaboradores como si fueran él.")
    category = ToolCategory.EMAIL
    required_inputs = ["email", "identifiers", "candidate_urls"]
    cache_prefix = "ghunt_"

    def pending(self, context):
        same_config = context.extra.get("ghunt_config_id") == config_id()
        checked = context.extra.get("ghunt_checked", []) if same_config else []
        resolved = context.extra.get("ghunt_resolved_gaia", []) if same_config else []
        account_count = sum(not key.startswith("drive:") for key in checked)
        drive_count = sum(key.startswith("drive:") for key in checked)
        result = []
        for query in queries(context):
            if query["kind"] == "gaia" and query["value"] in resolved:
                continue
            if query_key(query) in checked:
                continue
            if query["kind"] == "drive":
                if drive_count >= settings.ghunt_max_drive_files:
                    continue
                drive_count += 1
            else:
                if account_count >= settings.ghunt_max_queries:
                    continue
                account_count += 1
            result.append(query)
        return result

    def can_run(self, context):
        return settings.ghunt_enabled and bool(self.pending(context))

    async def execute(self, context: TargetContext):
        signature = config_id()
        if context.extra.get("ghunt_config_id") != signature:
            context.extra["ghunt_checked"] = []
            context.extra["ghunt_diagnostics"] = {}
            context.extra["ghunt_resolved_gaia"] = []
            context.extra["ghunt_config_id"] = signature
        checked = context.extra.setdefault("ghunt_checked", [])
        diagnostics = context.extra.setdefault("ghunt_diagnostics", {})
        state = capabilities()
        diagnostics["runtime"] = {key: state[key] for key in ("status", "version", "session_validated")}
        if state["status"] != "configured":
            # Record attempted coverage without a request, and allow later
            # activation to invalidate it through the configuration signature.
            for query in self.pending(context):
                key = query_key(query)
                checked.append(key)
                diagnostics[key] = {"status": state["status"], "requests": 0}
            return []
        findings = []
        deadline = asyncio.get_running_loop().time() + settings.ghunt_worker_timeout
        for query in self.pending(context):
            if query["kind"] == "gaia" and query["value"] in context.extra.get("ghunt_resolved_gaia", []):
                continue
            key = query_key(query)
            checked.append(key)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                diagnostics[key] = {"status": "time_budget_exhausted", "requests": 0}
                continue
            try:
                # One wall-clock budget for the batch, including session-lock
                # queueing. A slow service cannot multiply total run duration.
                async with asyncio.timeout(remaining):
                    result = await run_ghunt(query, state["services"])
            except asyncio.TimeoutError:
                result = {"status": "timeout", "services": {}}
            except Exception:
                result = {"status": "worker_error", "services": {}}
            diagnostics[key] = {"status": result["status"], "requests": result.get("requests", 0),
                "services": {name: item.get("status", "unknown") for name, item in result.get("services", {}).items()}}
            if result.get("error_type"):
                diagnostics[key]["error_type"] = result["error_type"]
            if result.get("warnings"):
                diagnostics[key]["warnings"] = result["warnings"]
            if result["status"] in {"observed", "not_found", "no_public_profile", "not_public", "not_found_or_inaccessible"}:
                diagnostics["runtime"]["session_validated"] = True
            if result["status"] == "observed":
                normalized = self.normalize(query, result)
                findings.extend(normalized)
                for finding in normalized:
                    if finding.entity_type == "google_account":
                        gaia = finding.metadata_info["gaia_id"]
                        resolved = context.extra.setdefault("ghunt_resolved_gaia", [])
                        if gaia not in resolved:
                            resolved.append(gaia)
            if result["status"] in {"session_invalid", "session_expired", "authentication_failed"}:
                diagnostics["runtime"]["status"] = result["status"]
                # Session failures affect the whole batch; do not hammer login.
                for remaining in self.pending(context):
                    other = query_key(remaining)
                    checked.append(other)
                    diagnostics[other] = {"status": result["status"], "requests": 0}
                break
        return findings

    def normalize(self, query, result):
        base = {"source_tool": self.name, "engine": "ghunt", "ghunt_version": "2.3.4",
                "access_context": "operator_session", "ownership_status": "unverified",
                "verification_status": "candidate", "query_kind": query["kind"],
                "queried_identifier": query["value"]}
        findings = []
        if query["kind"] == "drive":
            data = result.get("drive", {})
            folder = data.get("mime_type") == "application/vnd.google-apps.folder"
            url = f'https://drive.google.com/drive/folders/{query["value"]}' if folder else f'https://drive.google.com/file/d/{query["value"]}/view'
            findings.append(ToolFinding(entity_type="document", platform="google_drive", value=url,
                display_name=data.get("title") or "Documento público de Drive", confidence=0.6,
                metadata_info={**base, "url": url, "resource_kind": "drive_folder" if folder else "drive_file", "title": data.get("title"),
                    "mime_type": data.get("mime_type"), "created_at": data.get("created"), "modified_at": data.get("modified"),
                    "participants": data.get("users", []), "participant_scope": "document_collaborators_not_target_identifiers",
                    "access_scope": "anyone_with_link"}, evidence_urls=[url]))
            return findings
        profile = result.get("profile", {})
        gaia = str(profile.get("gaia_id", ""))
        if not re.fullmatch(r"[0-9]{10,30}", gaia) or query["kind"] == "gaia" and gaia != query["value"]:
            return []
        url = f"https://www.google.com/maps/contrib/{gaia}"
        evidence = "https://people-pa.googleapis.com/v2/people/lookup" if query["kind"] == "email" else "https://people-pa.googleapis.com/v2/people"
        metadata = {**base, "url": url, "resource_kind": "gaia_id", "gaia_id": gaia,
                    "account_exists": True, "technique": "ghunt_people_profile",
                    "discovered_identifiers": {gaia: "gaia_id"}, "name": profile.get("name") or None,
                    "last_updated": profile.get("last_updated"), "google_services": profile.get("services", []),
                    "user_types": profile.get("user_types", []), "container": "PROFILE"}
        for field in ("avatar_url", "cover_url"):
            if value := safe_url(profile.get(field)):
                metadata[field] = value
        # An exact lookup query is an association, not a public email declaration.
        if query["kind"] == "email":
            metadata["queried_email"] = query["value"]
        if profile.get("email"):
            metadata["profile_email"] = profile["email"]
        services = result.get("services", {})
        maps = services.get("maps", {})
        if maps.get("status") == "observed":
            metadata["maps_statistics"] = maps.get("statistics", {})
        findings.append(ToolFinding(entity_type="google_account", platform="google", value=url,
            display_name=profile.get("name") or f"Perfil Google · {gaia}", confidence=0.85,
            metadata_info=metadata, evidence_urls=[evidence]))
        calendar = services.get("calendar", {})
        if calendar.get("status") == "observed" and query["kind"] == "email":
            calendar_url = "https://calendar.google.com/calendar/embed?src=" + quote(query["value"], safe="")
            findings.append(ToolFinding(entity_type="search_mention", platform="google_calendar", value=calendar_url,
                display_name=calendar.get("summary") or "Calendario público", confidence=0.7,
                metadata_info={**base, "url": calendar_url, "access_context": "anonymous", "resource_kind": "public_calendar",
                    "time_zone": calendar.get("time_zone"), "events": calendar.get("events", []),
                    "truncated": calendar.get("truncated", False)}, evidence_urls=[calendar_url]))
        for player in services.get("play_games", {}).get("players", [])[:3]:
            identifier = player.get("id", "")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier):
                continue
            player_url = f"https://play.google.com/games/profile/{identifier}"
            findings.append(ToolFinding(entity_type="social_account", platform="google_play_games", value=player_url,
                display_name=player.get("name") or "Candidato de Play Games", confidence=0.4,
                metadata_info={**base, "url": player_url, "resource_kind": "player_id", "player_id": identifier,
                    "avatar_url": safe_url(player.get("avatar_url")), "technique": "ghunt_player_search",
                    "association": "search_candidate"}, evidence_urls=["https://play.google.com/googleplaygames"]))
        return findings
