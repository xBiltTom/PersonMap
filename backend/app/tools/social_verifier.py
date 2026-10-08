"""Enrich candidate profiles only when the response contains profile evidence."""

import asyncio
import logging
import json
import re
import time
from collections import Counter
from functools import lru_cache
from typing import Dict
from urllib.parse import urljoin, urlsplit, quote

import httpx
from bs4 import BeautifulSoup
from thefuzz import fuzz

from app.core.config import settings
from app.core.events import event_bus
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.telegram_profiles import observe_telegram_page
from app.tools.dataset_adapter import build_catalog
from app.tools.public_network import UnsafePublicURL, public_address
from app.tools.social_profiles import PROFILE_ROUTES, SocialProfile, normalize_web_url, parse_social_profile, social_host

logger = logging.getLogger(__name__)
HEADERS = {"Accept": "text/html,application/xhtml+xml"}
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
MENTION_RE = re.compile(r"(?<![\w@.+-])@([A-Za-z0-9_][A-Za-z0-9_.-]*)")
TERMINAL_STATES = {"verified", "not_found", "not_profile", "unsafe_url"}


@lru_cache(maxsize=1)
def _catalog_routes():
    routes = []
    for site in build_catalog():
        template = normalize_web_url((site.pretty_url or site.url).replace("{account}", "{username}"), keep_query=True)
        if template and "{username}" in template:
            pattern = re.escape(template).replace(re.escape("{username}"), r"([A-Za-z0-9_.-]+)")
            routes.append((re.compile(pattern, re.IGNORECASE), site))
    return routes


def _candidate_profile(url):
    profile = parse_social_profile(url)
    if profile:
        return profile
    normalized = normalize_web_url(url, keep_query=True)
    if not normalized:
        return None
    if social_host(normalized) in PROFILE_ROUTES or social_host(normalized) in {"telegram.me", "telegram.dog"} or social_host(normalized).endswith(".t.me"):
        return None  # Catalog templates cannot override reserved provider routes.
    for pattern, site in _catalog_routes():
        match = pattern.fullmatch(normalized)
        if match and site.accepts_username(match[1]):
            return SocialProfile(site.name, match[1], normalized)
    return None


def _safe_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or any(ch.isspace() or ord(ch) < 32 for ch in url)):
        raise UnsafePublicURL("Invalid public URL")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafePublicURL("Local hostname")
    try:
        allowed = public_address(host)
    except ValueError:
        return  # DNS is validated and pinned by PublicNetworkBackend.
    if not allowed:
        raise UnsafePublicURL("Non-public IP address")


class SocialVerifierTool(BaseTool):
    name = "social_verifier"
    description = "Extrae metadatos de perfiles con evidencia de existencia y conserva el estado de la consulta"
    category = ToolCategory.SOCIAL
    required_inputs = ["candidate_urls"]

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.extra.get("candidate_urls"))

    async def execute(self, context: TargetContext) -> list[ToolFinding]:
        outcomes = context.extra.setdefault("social_verifier_results", {})
        attempts = context.extra.setdefault("social_verifier_attempts", {})
        completed_profiles = {
            profile.url
            for url, result in outcomes.items()
            if result.get("status") in TERMINAL_STATES
            and (profile := _candidate_profile(url)) is not None
        }
        pending = []
        seen = set()
        for raw in context.extra.get("candidate_urls", []):
            if not isinstance(raw, str):
                continue
            # Do not discard query parameters until the requested resource is
            # known: a query can determine whether a URL is a profile.
            url = raw.strip()
            profile = _candidate_profile(url)
            identity = profile.url if profile else url
            if identity in seen or identity in completed_profiles or outcomes.get(url, {}).get("status") in TERMINAL_STATES:
                continue
            seen.add(identity)
            if attempts.get(identity, 0) >= 2:
                continue
            if identity not in attempts and len(attempts) >= settings.social_verify_max_urls:
                continue
            pending.append(url)
            attempts[identity] = attempts.get(identity, 0) + 1
        if not pending:
            return []
        semaphore = asyncio.Semaphore(settings.tool_concurrency_budget(settings.social_verify_concurrency))
        async with http_client.build_client(timeout=10.0, headers=HEADERS, public_only=True, follow_redirects=False) as client:
            async def verify(url):
                async with semaphore:
                    try:
                        async with asyncio.timeout(settings.social_verify_url_timeout):
                            return await self.verify_url(client, url, context)
                    except TimeoutError:
                        self._record(context, url, "error", error="total_timeout")
                        return None
            results = await asyncio.gather(*(verify(url) for url in pending))
        counts = dict(Counter(outcomes[url]["status"] for url in pending))
        context.extra["social_verifier_stats"] = dict(Counter(item["status"] for item in outcomes.values()))
        investigation_id = context.extra.get("investigation_id")
        if investigation_id:
            await event_bus.publish(investigation_id, {
                "type": "log", "phase": "verification", "tool": self.name,
                "checked": len(pending), "statuses": counts,
                "message": f"[{self.name}] {len(pending)} URLs consultadas: {counts}",
                "timestamp": time.time(),
            })
        return [finding for finding in results if finding is not None]

    def _record(self, context, url, status, **details):
        context.extra.setdefault("social_verifier_results", {})[url] = {"status": status, **details}

    async def verify_url(self, client: httpx.AsyncClient, url: str, context: TargetContext) -> ToolFinding | None:
        try:
            _safe_url(url)
            requested = _candidate_profile(url)
            if requested is None:
                self._record(context, url, "not_profile")
                return None
            if requested.platform == "tiktok":
                embedded = await self._tiktok_embed(client, requested, url, context)
                if embedded is not None:
                    return embedded
            current = requested.url if requested.platform == "telegram" else url
            for _ in range(6):
                _safe_url(current)
                resp = await client.get(current, follow_redirects=False)
                if resp.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = resp.headers.get("location")
                if not location:
                    self._record(context, url, "error", error="redirect_without_location")
                    return None
                current = urljoin(str(resp.url), location)
            else:
                self._record(context, url, "error", error="too_many_redirects")
                return None
            status = resp.status_code
            details = {"http_status": status, "final_url": str(resp.url)}
            if status != 200:
                state = "not_found" if status in {404, 410} else "blocked" if status in {401, 403, 429, 999} else "error"
                self._record(context, url, state, **details)
                return None
            if resp.headers.get("content-type", "").split(";", 1)[0].lower() not in {"text/html", "application/xhtml+xml", ""}:
                self._record(context, url, "not_profile", **details)
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            title = self._get_meta(soup, "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
            bio = self._get_meta(soup, "og:description") or self._get_meta(soup, "description") or ""
            image = self._get_meta(soup, "og:image") or ""
            final_profile = _candidate_profile(str(resp.url))
            visible_title = soup.title.get_text(" ", strip=True) if soup.title else ""
            title_lower = f"{title} {visible_title}".lower()
            if any(marker in title_lower for marker in ("log in", "login", "sign in", "iniciar sesión")):
                self._record(context, url, "blocked", **details)
                return None
            if any(marker in title_lower for marker in ("just a moment", "access denied", "captcha", "verify you are human", "security check")):
                self._record(context, url, "blocked", **details)
                return None
            yt_identity = self._get_meta(soup, "channelId") if requested.platform == "youtube" else None
            yt_alias = bool(final_profile and requested.platform == final_profile.platform == "youtube"
                            and requested.resource_kind == "channel_id" and yt_identity == requested.username)
            if (not requested or not final_profile
                    or requested.platform != final_profile.platform
                    or (requested.username.lower() != final_profile.username.lower() and not yt_alias)
                    or any(marker in title_lower for marker in ("log in", "login", "sign in", "page not found", "user not found", "profile not found", "page isn't available", "page doesn’t exist", "iniciar sesión", "página no encontrada"))):
                self._record(context, url, "not_profile", **details)
                return None
            username = final_profile.username
            og_type = (self._get_meta(soup, "og:type") or "").lower()
            profile_username = self._get_meta(soup, "profile:username") or ""
            signals = []
            telegram = None
            if requested.platform == "telegram":
                telegram = observe_telegram_page(soup, username)
                if telegram.status != "verified":
                    self._record(context, url, telegram.status, reason=telegram.reason, **details)
                    return None
                title, bio = telegram.title, telegram.bio
                signals.extend(telegram.signals)
            if requested.platform == "snapchat":
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    try:
                        data = json.loads(script.string or script.get_text())
                        user = data.get("props", {}).get("pageProps", {}).get("userProfile", {}).get("userInfo", {})
                        if isinstance(user.get("username"), str) and user["username"].lower() == username.lower():
                            signals.append("snapchat_user_info")
                    except (ValueError, AttributeError, TypeError):
                        pass
            if yt_identity and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", yt_identity) and (requested.resource_kind != "channel_id" or requested.username == yt_identity):
                signals.append("youtube_channel_id")
            if og_type == "profile" and title and (profile_username.lower() == username.lower() or username.lower() in f"{title} {bio}".lower()):
                signals.append("og_profile")
            if profile_username.lower() == username.lower():
                signals.append("profile_username")
            if re.search(r"(?<![\w])" + re.escape(username) + r"(?![\w])", f"{title} {visible_title} {bio}", re.IGNORECASE) and (bio or image):
                signals.append("username_in_metadata")
            if not signals:
                self._record(context, url, "inconclusive", **details)
                return None
            declared_url = self._get_meta(soup, "og:url")
            if not declared_url:
                link = soup.find("link", rel="canonical")
                declared_url = str(link.get("href", "")) if link else None
            canonical = final_profile.url
            canonical_accepted = False
            if declared_url:
                declared_profile = _candidate_profile(urljoin(str(resp.url), declared_url))
                if declared_profile and declared_profile.platform == final_profile.platform and declared_profile.username.lower() == username.lower():
                    canonical = declared_profile.url
                    canonical_accepted = True
            emails = list(dict.fromkeys(EMAIL_RE.findall(bio)))
            bio_without_emails = EMAIL_RE.sub(" ", bio)
            usernames = list(dict.fromkeys(u.rstrip(".-") for u in MENTION_RE.findall(bio_without_emails)))
            score, breakdown = self._compute_verification_score(title, bio, context.full_name, context.university, context.email)
            metadata = {
                "source_tool": self.name, "username": username,
                "resource_kind": final_profile.resource_kind, "profile_url": canonical,
                "channel_id": yt_identity,
                "telegram_peer_type": telegram.peer_type if telegram else None,
                "candidate_origin": context.extra.get("derived_profile_candidates", {}).get(url),
                "og_title": title, "bio": bio,
                # Preview images are not profile avatars.
                "og_image": image, "canonical_url": canonical,
                "requested_url": url, "final_url": str(resp.url),
                "declared_canonical_url": declared_url,
                "canonical_accepted": canonical_accepted,
                "extracted_usernames": usernames, "extracted_emails": emails,
                "verification_status": "verified", "profile_signals": signals,
                "verification_breakdown": breakdown,
            }
            self._record(context, url, "verified", **details)
            return ToolFinding(entity_type="social_account", platform=final_profile.platform,
                value=canonical, display_name=title or canonical, metadata_info=metadata,
                confidence=score, evidence_urls=list(dict.fromkeys([url, str(resp.url)])))
        except UnsafePublicURL:
            self._record(context, url, "unsafe_url")
        except (httpx.HTTPError, ValueError) as exc:
            self._record(context, url, "error", error=type(exc).__name__)
            logger.debug("Social verification request failed (%s)", type(exc).__name__)
        return None

    async def _tiktok_embed(self, client, profile, url, context):
        endpoint = "https://www.tiktok.com/oembed?url=" + quote(profile.url, safe="")
        try:
            # Automatic redirects stay disabled on the pinned public client.
            resp = await client.get(endpoint, follow_redirects=False)
            if resp.status_code != 200:
                return None  # Private/underage profiles may not support embedding.
            data = resp.json()
            author = parse_social_profile(data.get("author_url", ""))
            if not author or author.platform != "tiktok" or author.username.lower() != profile.username.lower():
                return None
            self._record(context, url, "verified", http_status=200, final_url=author.url, adapter="tiktok_oembed")
            return ToolFinding(
                entity_type="social_account", platform="tiktok", value=author.url,
                display_name=str(data.get("author_name") or profile.username), confidence=0.5,
                evidence_urls=[url, endpoint],
                metadata_info={"source_tool": self.name, "username": author.username,
                               "profile_url": author.url, "canonical_url": author.url,
                               "requested_url": url, "verification_status": "verified",
                               "profile_signals": ["tiktok_oembed_author"],
                               "candidate_origin": context.extra.get("derived_profile_candidates", {}).get(url)},
            )
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            return None

    def _get_meta(self, soup: BeautifulSoup, property_name: str) -> str | None:
        tag = soup.find("meta", property=property_name) or soup.find("meta", attrs={"name": property_name}) or soup.find("meta", attrs={"itemprop": property_name})
        return str(tag["content"]).strip() if tag and tag.get("content") else None

    def _compute_verification_score(
        self,
        title: str,
        bio: str,
        target_name: str | None,
        target_university: str | None,
        target_email: str | None,
    ) -> tuple[float, Dict[str, float]]:
        score = 0.5  # Base profile existence
        breakdown = {"base": 0.5}

        # Check full name similarity in title or bio
        if target_name and (title or bio):
            combined_text = f"{title} {bio}"
            name_ratio = fuzz.partial_ratio(target_name.lower(), combined_text.lower()) / 100.0
            breakdown["name_match_ratio"] = name_ratio
            if name_ratio > 0.85:
                score += 0.25
            elif name_ratio > 0.65:
                score += 0.15

        # Check university in bio
        if target_university and bio:
            uni_ratio = fuzz.partial_ratio(target_university.lower(), bio.lower()) / 100.0
            breakdown["university_match_ratio"] = uni_ratio
            if uni_ratio > 0.75:
                score += 0.20

        # Check email domain or exact email in bio
        if target_email and bio:
            if target_email.lower() in bio.lower():
                score += 0.25
                breakdown["email_in_bio"] = 1.0

        score = min(max(score, 0.1), 0.99)
        return score, breakdown
