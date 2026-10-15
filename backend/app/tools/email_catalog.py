# SPDX-License-Identifier: GPL-3.0-or-later
"""Reviewed query/validation techniques adapted from megadose/Holehe.

Upstream snapshot: 14da70f588538936b20d238783c5e28a0772a2b3 (2024-09-10).
See docs/HOLEHE.md and docs/vendor/holehe for attribution and upstream license.
Modern request references: kaifcodec/user-scanner, MIT, snapshot 38ce09e;
see docs/vendor/user-scanner for attribution and license.
Parsers intentionally reject unknown schemas instead of treating them as false.
"""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any

from app.core.config import settings

HOLEHE_COMMIT = "14da70f588538936b20d238783c5e28a0772a2b3"
ENGINE_VERSION = 2


@dataclass(frozen=True)
class EmailProbe:
    key: str
    platform: str
    url: str
    parser: str
    home: str
    category: str = "services"
    method: str = "GET"
    send: str = "params"
    payload: dict = field(default_factory=lambda: {"email": "{email}"})
    warmup: str = ""
    csrf: str = ""
    headers: dict = field(default_factory=dict)
    upstream: str = ""
    reference: str = ""
    response_codes: tuple[int, ...] = (200,)


# Only query or explicit validation endpoints. No account creation, password
# submission, recovery dispatch, mailbox access, or operator Google session.
PROBES = (
    EmailProbe("spotify", "Spotify", "https://spclient.wg.spotify.com/signup/public/v1/account", "spotify", "https://open.spotify.com", "music", payload={"validate": "1", "email": "{email}"}, upstream="music/spotify.py"),
    EmailProbe("twitter", "Twitter/X", "https://api.twitter.com/i/users/email_available.json", "taken", "https://x.com", "social", upstream="social_media/twitter.py"),
    EmailProbe("github", "GitHub", "https://github.com/email_validity_checks", "github", "https://github.com", "coding", "POST", "data", {"value": "{email}"}, "https://github.com/signup", "github", upstream="programing/github.py", reference="user-scanner/email_scan/dev/github.py@38ce09e", response_codes=(200, 422)),
    EmailProbe("duolingo", "Duolingo", "https://www.duolingo.com/2017-06-30/users", "duolingo", "https://www.duolingo.com", "education", upstream="learning/duolingo.py"),
    EmailProbe("firefox", "Firefox Accounts", "https://api.accounts.firefox.com/v1/account/status", "exists", "https://accounts.firefox.com", "tech", "POST", "json", upstream="software/firefox.py"),
    EmailProbe("chess", "Chess.com", "https://www.chess.com/callback/email/available", "available", "https://chess.com", "gaming"),
    EmailProbe("lastpass", "LastPass", "https://lastpass.com/create_account.php", "lastpass", "https://lastpass.com", "security", payload={"check": "avail", "skipcontent": "1", "mistype": "1", "username": "{email}"}, upstream="software/lastpass.py"),
    EmailProbe("adobe", "Adobe", "https://auth.services.adobe.com/signin/v2/users/accounts", "accounts", "https://adobe.com", "tech", "POST", "json", {"username": "{email}", "usernameType": "EMAIL"}, headers={"x-ims-clientid": "BehanceWebSusi1"}, reference="user-scanner/email_scan/creator/adobe.py@38ce09e"),
    EmailProbe("steam", "Steam", "https://store.steampowered.com/join/ajaxcheckemailverified", "steam", "https://store.steampowered.com", "gaming", "POST", "data"),
    EmailProbe("strava", "Strava", "https://www.strava.com/athletes/email_unique", "text_available", "https://strava.com", "hobby", warmup="https://www.strava.com/register/free", csrf="meta", upstream="social_media/strava.py"),
    EmailProbe("wordpress", "WordPress", "https://public-api.wordpress.com/rest/v1.1/users/{email}/auth-options", "wordpress", "https://wordpress.com", "publishing", payload={"http_envelope": "1", "locale": "en"}, upstream="cms/wordpress.py"),
    EmailProbe("replit", "Replit", "https://replit.com/data/user/exists", "exists", "https://replit.com", "coding", "POST", "json", upstream="programing/replit.py"),
    EmailProbe("anydo", "Any.do", "https://sm-prod2.any.do/check_email", "user_exists", "https://www.any.do", "productivity", "POST", "json", headers={"X-Platform": "3", "Origin": "https://desktop.any.do"}, upstream="productivity/anydo.py"),
    EmailProbe("pinterest", "Pinterest", "https://www.pinterest.com/_ngjs/resource/EmailExistsResource/get/", "pinterest", "https://www.pinterest.com", "social", payload={"source_url": "/", "data": {"options": {"email": "{email}"}, "context": {}}}, upstream="social_media/pinterest.py"),
    EmailProbe("patreon", "Patreon", "https://www.patreon.com/api/email/available", "patreon", "https://www.patreon.com", "social", "POST", "json", {"data": {"attributes": {"email": "{email}"}, "relationships": {}}}, headers={"Content-Type": "application/vnd.api+json"}, upstream="social_media/patreon.py"),
    EmailProbe("plurk", "Plurk", "https://www.plurk.com/Users/isEmailFound", "text_exists", "https://www.plurk.com", "social", "POST", "data", upstream="social_media/plurk.py"),
    EmailProbe("deliveroo", "Deliveroo", "https://consumer-ow-api.deliveroo.com/orderapp/v1/check-email", "registered", "https://deliveroo.com", "shopping", "POST", "json", {"email_address": "{email}"}, headers={"X-Roo-Client": "orderweb-client", "X-Roo-Country": "fr"}, upstream="shopping/deliveroo.py"),
    EmailProbe("issuu", "Issuu", "https://issuu.com/call/signup/check-email/{email}", "issuu", "https://issuu.com", "publishing", payload={}, upstream="software/issuu.py"),
    EmailProbe("amocrm", "Kommo (amoCRM)", "https://www.kommo.com/account/check_login.php", "amocrm", "https://www.kommo.com", "productivity", "POST", "data", {"LOGIN": "{email}"}, upstream="crm/amocrm.py", reference="canonical redirect observed 2026-10-14"),
    EmailProbe("diigo", "Diigo", "https://www.diigo.com/user_mana2/check_email", "diigo", "https://www.diigo.com", "education", upstream="learning/diigo.py"),
    EmailProbe("lastfm", "Last.fm", "https://www.last.fm/join/partial/validate", "lastfm", "https://www.last.fm", "music", "POST", "data", {"userName": "", "email": "{email}"}, "https://www.last.fm/join", "lastfm", upstream="music/lastfm.py"),
    EmailProbe("eventbrite", "Eventbrite", "https://www.eventbrite.com/api/v3/users/lookup/", "exists", "https://www.eventbrite.com", "events", "POST", "json", warmup="https://www.eventbrite.com/signin/", csrf="eventbrite", upstream="products/eventbrite.py"),
    EmailProbe("codepen", "CodePen", "https://codepen.io/accounts/duplicate_check", "codepen", "https://codepen.io", "coding", "POST", "data", {"attribute": "email", "value": "{email}", "context": "user"}, "https://codepen.io/accounts/signup/user/free", "meta", upstream="programing/codepen.py"),
    EmailProbe("codecademy", "Codecademy", "https://www.codecademy.com/register/validate", "codecademy", "https://www.codecademy.com", "education", "POST", "json", {"user": {"email": "{email}"}}, "https://www.codecademy.com/register", "meta", upstream="programing/codecademy.py"),
    EmailProbe("envato", "Envato", "https://account.envato.com/api/validate_email", "envato", "https://account.envato.com", "design", "POST", "data", upstream="shopping/envato.py"),
    EmailProbe("atlassian", "Atlassian", "https://id.atlassian.com/rest/check-username", "atlassian", "https://id.atlassian.com", "productivity", "POST", "json", {"username": "{email}"}, headers={"Referer": "https://id.atlassian.com/login"}, upstream="cms/atlassian.py", reference="user-scanner/email_scan/dev/atlassian.py@38ce09e; social_login observed 2026-10-14"),
    EmailProbe("orcid", "ORCID", "https://orcid.org/registerEmailValidate.json", "orcid", "https://orcid.org", "education", "POST", "json", {"email": {"value": "{email}"}, "emailConfirm": {"value": None}}, reference="ORCID/ORCID-Source RegistrationController.regEmailValidate (read-only validation)"),
    EmailProbe("miro", "Miro", "https://svc.eu01.miro.com/api/sign-in/v1/email/validate", "miro", "https://miro.com", "productivity", "POST", "json", headers={"Origin": "https://miro.com"}, reference="Miro auth-ICihi__yo2WUdxvRPLvpz public signup client; authentication hints do not prove registration"),
)

EXCLUDED = {
    "discord": "account_creation_endpoint",
    "tumblr": "account_creation_endpoint",
    "google": "handled_by_ghunt",
    "gravatar": "handled_by_gravatar_deep",
    "vsco": "upstream_embeds_static_bearer_token",
    "quora": "known_non_discriminating_response",
}


def selected_probes():
    configured = set(settings.email_enum_sites)
    return [probe for probe in PROBES if not configured or probe.key in configured]


def capabilities():
    return {"engine_version": ENGINE_VERSION, "holehe_commit": HOLEHE_COMMIT,
            "holehe_last_commit": "2024-09-10", "catalog_size": len(PROBES),
            "selected": [probe.key for probe in selected_probes()], "excluded": EXCLUDED,
            "observation_only": [probe.key for probe in selected_probes() if probe.parser == "miro"],
            "unknown_sites": sorted(set(settings.email_enum_sites) - {probe.key for probe in PROBES}),
            "max_emails": settings.email_enum_max_emails,
            "concurrency": settings.tool_concurrency_budget(settings.email_enum_concurrency),
            "request_timeout": settings.email_enum_request_timeout,
            "probe_timeout": settings.email_enum_probe_timeout,
            "batch_timeout": settings.email_enum_batch_timeout,
            "result_scope": "registration_signal_not_profile", "live_coverage_verified": False}


def config_id():
    return hashlib.sha256(json.dumps({**capabilities(), "probes": [asdict(p) for p in selected_probes()]}, sort_keys=True).encode()).hexdigest()


def at(data: Any, *path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def boolean(value, *, inverted=False):
    return not value if inverted and type(value) is bool else value if type(value) is bool else None


def parse_registration(parser, response):
    """True/False only on an explicit documented signal; None is unknown."""
    if parser in {"github", "lastpass", "text_exists", "text_available", "diigo", "codepen", "envato"}:
        body = response.text.strip()
        if parser == "github":
            from bs4 import BeautifulSoup
            visible = BeautifulSoup(body, "html.parser").get_text(" ", strip=True).lower()
            if response.status_code == 422 and any(marker in visible for marker in (
                    "email is already taken", "email address is already associated with an account")):
                return True
            if response.status_code == 200 and visible == "email is available":
                return False
        if response.status_code != 200:
            return None
        if parser == "lastpass":
            return {"no": True, "ok": False}.get(body)
        if parser == "text_exists":
            return {"True": True, "False": False}.get(body)
        if parser == "text_available":
            return {"false": True, "true": False}.get(body)
        if parser == "diigo":
            return {"0": True, "1": False}.get(body)
        if parser == "codepen" and body == "That Email is already taken.":
            return True
        if parser == "envato" and body == "Email is already in use":
            return True
        return None
    try:
        data = response.json()
    except (ValueError, UnicodeError):
        return None
    if parser == "accounts" and isinstance(data, list):
        if not data:
            return False
        # Current Adobe API returns a list, including federated accounts.
        valid = all(isinstance(account, dict) and isinstance(account.get("authenticationMethods"), list)
                    and account["authenticationMethods"]
                    and all(isinstance(method, dict) and isinstance(method.get("id"), str) and method["id"]
                            for method in account["authenticationMethods"]) for account in data)
        return True if valid else None
    if not isinstance(data, dict):
        return None
    if parser == "atlassian":
        action = data.get("action")
        if action == "signup":
            return False
        if isinstance(action, str) and action in {"no_action", "redirect", "social_login"}:
            return True
        return None
    if parser == "orcid":
        errors = at(data, "email", "errors")
        if not isinstance(errors, list):
            return None
        known = {"orcid.frontend.verify.duplicate_email", "orcid.frontend.verify.deactivated_email",
                 "orcid.frontend.verify.unclaimed_email"}
        if any(isinstance(error, str) and error in known for error in errors):
            return True
        return False if not errors else None
    if parser == "available":
        # Chess.com now returns isEmailAvailable; keep the former schema only
        # when it is explicit and does not contradict the current field.
        current, legacy = data.get("isEmailAvailable"), data.get("available")
        if type(current) is bool and type(legacy) is bool and current != legacy:
            return None
        return boolean(current if "isEmailAvailable" in data else legacy, inverted=True)
    if parser in {"exists", "taken", "registered", "user_exists", "available"}:
        return boolean(data.get(parser), inverted=parser == "available")
    if parser == "spotify":
        value = data.get("status")
        return {1: False, 20: True}.get(value) if type(value) is int else None
    if parser in {"duolingo", "accounts"}:
        value = data.get("users" if parser == "duolingo" else "accounts")
        return bool(value) if isinstance(value, list) and all(isinstance(item, dict) for item in value) else None
    if parser == "steam":
        # Steam code 84 means rate limiting, never proof of registration.
        return boolean(data.get("bEmailAlreadyTaken"))
    if parser == "pinterest":
        return boolean(at(data, "resource_response", "data"))
    if parser == "patreon":
        return boolean(at(data, "data", "is_available"), inverted=True)
    if parser == "issuu":
        value = data.get("status")
        return {"unavailable": True, "available": False}.get(value) if isinstance(value, str) else None
    if parser == "amocrm":
        value = data.get("status")
        return {"used": True, "free": False}.get(value) if isinstance(value, str) else None
    if parser == "wordpress":
        body = data.get("body")
        if not isinstance(body, dict):
            return None
        if body.get("error") == "unknown_user":
            return False
        # email_verified=False still describes an existing, unverified user.
        return True if type(body.get("email_verified")) is bool else None
    if parser == "lastfm":
        email = data.get("email")
        if not isinstance(email, dict):
            return None
        if "Sorry, that email address is already registered to another account." in email.get("error_messages", []):
            return True
        return False if email.get("valid") is True else None
    if parser == "codecademy":
        errors = at(data, "errors", "email")
        return True if errors == ["is already taken"] else None
    return None
