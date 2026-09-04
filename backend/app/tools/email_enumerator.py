import asyncio
import hashlib
from typing import Any, Dict, List, Optional
import httpx
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class EmailEnumeratorTool(BaseTool):
    """
    Passive Email Enumeration Tool inspired by Holehe.
    Checks whether an email address is registered across 20+ major web platforms
    without sending any verification emails or alerting the target.
    """

    name = "email_enumerator"
    description = "Chequeo pasivo y silencioso de registro de email en 20+ plataformas masivas (Spotify, Discord, GitHub, Duolingo, etc.)"
    category = ToolCategory.EMAIL
    required_inputs = ["email"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        emails = context.all_emails()
        if not emails:
            return findings

        async with http_client.build_client(timeout=7.0) as client:
            for email in emails:
                clean_email = email.strip().lower()
                if not clean_email or "@" not in clean_email:
                    continue

                probes = [
                    self._check_spotify(client, clean_email),
                    self._check_discord(client, clean_email),
                    self._check_twitter(client, clean_email),
                    self._check_github(client, clean_email),
                    self._check_duolingo(client, clean_email),
                    self._check_pinterest(client, clean_email),
                    self._check_firefox(client, clean_email),
                    self._check_wordpress(client, clean_email),
                    self._check_patreon(client, clean_email),
                    self._check_chess(client, clean_email),
                    self._check_buymeacoffee(client, clean_email),
                    self._check_gravatar(client, clean_email),
                    self._check_lastpass(client, clean_email),
                    self._check_adobe(client, clean_email),
                    self._check_steam(client, clean_email),
                    self._check_strava(client, clean_email),
                    self._check_tumblr(client, clean_email),
                    self._check_vimeo(client, clean_email),
                    self._check_dockerhub(client, clean_email),
                    self._check_quora(client, clean_email),
                ]

                results = await asyncio.gather(*probes, return_exceptions=True)

                for res in results:
                    if isinstance(res, dict) and res.get("registered"):
                        platform = res["platform"]
                        profile_url = res.get("url", f"https://{platform.lower().replace(' ', '')}.com")
                        findings.append(
                            ToolFinding(
                                entity_type="social_account",
                                platform=platform,
                                value=f"{platform} ({clean_email})",
                                display_name=f"{platform}: Cuenta Activa",
                                confidence=0.90,
                                metadata_info={
                                    "email": clean_email,
                                    "platform": platform,
                                    "registered": True,
                                    "category": res.get("category", "services"),
                                    "url": profile_url,
                                    "source_tool": "email_enumerator",
                                },
                            )
                        )

        return findings

    # --- INDIVIDUAL PASSIVE PROBES ---

    async def _check_spotify(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://spclient.wg.spotify.com/signup/public/v2/account/create"
            resp = await client.post(url, data={"validate": "1", "email": email})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == 20:  # Email exists
                    return {"platform": "Spotify", "registered": True, "category": "music", "url": "https://open.spotify.com"}
        except Exception:
            pass
        return None

    async def _check_discord(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://discord.com/api/v9/auth/register"
            resp = await client.post(
                url,
                json={"email": email, "username": "validatinguser", "password": "DummyPassword123!", "consent": True},
            )
            data = resp.json()
            # 20001 = EMAIL_ALREADY_REGISTERED
            if resp.status_code in [400, 200] and ("EMAIL_ALREADY_REGISTERED" in resp.text or data.get("code") == 20001):
                return {"platform": "Discord", "registered": True, "category": "social", "url": "https://discord.com"}
        except Exception:
            pass
        return None

    async def _check_twitter(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://api.twitter.com/i/users/email_available.json?email={email}"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("taken") is True:
                    return {"platform": "Twitter/X", "registered": True, "category": "social", "url": "https://x.com"}
        except Exception:
            pass
        return None

    async def _check_github(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://github.com/signup_check/email"
            resp = await client.post(url, data={"value": email})
            if resp.status_code == 422 and "already" in resp.text.lower():
                return {"platform": "GitHub", "registered": True, "category": "coding", "url": "https://github.com"}
        except Exception:
            pass
        return None

    async def _check_duolingo(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://www.duolingo.com/2017-06-30/users?email={email}"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                users = data.get("users", [])
                if len(users) > 0:
                    username = users[0].get("username")
                    profile_url = f"https://www.duolingo.com/profile/{username}" if username else "https://www.duolingo.com"
                    return {"platform": "Duolingo", "registered": True, "category": "education", "url": profile_url}
        except Exception:
            pass
        return None

    async def _check_pinterest(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://api.pinterest.com/v3/register/email/?email={email}"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data", {}).get("exists") is True or "already" in resp.text.lower():
                    return {"platform": "Pinterest", "registered": True, "category": "images", "url": "https://pinterest.com"}
        except Exception:
            pass
        return None

    async def _check_firefox(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://api.accounts.firefox.com/v1/account/status"
            resp = await client.post(url, json={"email": email})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("exists") is True:
                    return {"platform": "Firefox Accounts", "registered": True, "category": "tech", "url": "https://firefox.com"}
        except Exception:
            pass
        return None

    async def _check_wordpress(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://public-api.wordpress.com/rest/v1.1/users/{email}/auth-options"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("error") and ("has_password" in data or "username" in data):
                    return {"platform": "WordPress", "registered": True, "category": "blog", "url": "https://wordpress.com"}
        except Exception:
            pass
        return None

    async def _check_patreon(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://www.patreon.com/api/auth/email-check"
            resp = await client.post(url, json={"email": email})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("is_registered") is True:
                    return {"platform": "Patreon", "registered": True, "category": "art", "url": "https://patreon.com"}
        except Exception:
            pass
        return None

    async def _check_chess(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://www.chess.com/callback/email/available?email={email}"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                # If available is False, the email is already in use
                if data.get("available") is False:
                    return {"platform": "Chess.com", "registered": True, "category": "gaming", "url": "https://chess.com"}
        except Exception:
            pass
        return None

    async def _check_buymeacoffee(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://www.buymeacoffee.com/api/v1/check-email"
            resp = await client.post(url, json={"email": email})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") is False or data.get("available") is False:
                    return {"platform": "BuyMeACoffee", "registered": True, "category": "business", "url": "https://buymeacoffee.com"}
        except Exception:
            pass
        return None

    async def _check_gravatar(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            md5_hash = hashlib.md5(email.encode()).hexdigest()
            url = f"https://en.gravatar.com/{md5_hash}.json"
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"platform": "Gravatar", "registered": True, "category": "social", "url": f"https://gravatar.com/{md5_hash}"}
        except Exception:
            pass
        return None

    async def _check_lastpass(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://lastpass.com/create_account.php?check=all&email={email}"
            resp = await client.get(url)
            if resp.status_code == 200 and "EMAIL_ALREADY_TAKEN" in resp.text:
                return {"platform": "LastPass", "registered": True, "category": "security", "url": "https://lastpass.com"}
        except Exception:
            pass
        return None

    async def _check_adobe(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://auth.services.adobe.com/signin/v2/users/accounts"
            resp = await client.post(url, json={"username": email})
            if resp.status_code == 200:
                data = resp.json()
                if len(data.get("accounts", [])) > 0:
                    return {"platform": "Adobe", "registered": True, "category": "tech", "url": "https://adobe.com"}
        except Exception:
            pass
        return None

    async def _check_steam(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://store.steampowered.com/join/ajaxcheckemailverified"
            resp = await client.post(url, data={"email": email})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("bEmailAlreadyTaken") is True or data.get("success") == 84:
                    return {"platform": "Steam", "registered": True, "category": "gaming", "url": "https://store.steampowered.com"}
        except Exception:
            pass
        return None

    async def _check_strava(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://www.strava.com/athletes"
            resp = await client.post(url, data={"athlete[email]": email})
            if resp.status_code in [422, 200] and "has already been taken" in resp.text:
                return {"platform": "Strava", "registered": True, "category": "hobby", "url": "https://strava.com"}
        except Exception:
            pass
        return None

    async def _check_tumblr(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://www.tumblr.com/svc/account/register"
            resp = await client.post(url, json={"email": email, "password": "DummyPassword123!"})
            if resp.status_code in [400, 200] and "already has an account" in resp.text:
                return {"platform": "Tumblr", "registered": True, "category": "blog", "url": "https://tumblr.com"}
        except Exception:
            pass
        return None

    async def _check_vimeo(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://vimeo.com/log_in"
            resp = await client.post(url, data={"email": email, "password": "DummyPassword123!"})
            if resp.status_code in [400, 401, 200] and "already registered" in resp.text.lower():
                return {"platform": "Vimeo", "registered": True, "category": "video", "url": "https://vimeo.com"}
        except Exception:
            pass
        return None

    async def _check_dockerhub(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://hub.docker.com/v2/users/signup/"
            resp = await client.post(url, json={"email": email, "username": "testdummy1234", "password": "Password123!"})
            if resp.status_code in [400, 409] and "email" in resp.text.lower() and "already" in resp.text.lower():
                return {"platform": "DockerHub", "registered": True, "category": "tech", "url": "https://hub.docker.com"}
        except Exception:
            pass
        return None

    async def _check_quora(self, client: httpx.AsyncClient, email: str) -> Optional[Dict[str, Any]]:
        try:
            url = "https://www.quora.com/web/signup/check_email"
            resp = await client.post(url, data={"email": email})
            if resp.status_code == 200 and ("false" in resp.text.lower() or "taken" in resp.text.lower()):
                return {"platform": "Quora", "registered": True, "category": "social", "url": "https://quora.com"}
        except Exception:
            pass
        return None
