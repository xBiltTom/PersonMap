import asyncio
import hashlib
import secrets
import string
from typing import Any, Awaitable, Callable, Dict, List, Optional
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
    description = (
        "Chequeo pasivo de registro de correo en plataformas masivas mediante sus "
        "endpoints de validación de alta (Spotify, Discord, GitHub, Duolingo, Steam...)"
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email"]

    # Sondas que no se limitan a preguntar si el correo está libre: envían un
    # alta completa. Con un correo inventado podrían crear una cuenta de verdad
    # en un servicio ajeno, así que a estas no se les pasa el control negativo.
    SUBMITS_A_SIGNUP = {"_check_discord", "_check_strava", "_check_tumblr"}

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

                checks = [
                    self._check_spotify,
                    self._check_discord,
                    self._check_twitter,
                    self._check_github,
                    self._check_duolingo,
                    self._check_firefox,
                    self._check_chess,
                    self._check_lastpass,
                    self._check_adobe,
                    self._check_steam,
                    self._check_strava,
                    self._check_tumblr,
                ]

                results = await asyncio.gather(
                    *(check(client, clean_email) for check in checks),
                    return_exceptions=True,
                )

                for check, res in zip(checks, results):
                    if not (isinstance(res, dict) and res.get("registered")):
                        continue
                    if getattr(check, "__name__", "") in self.SUBMITS_A_SIGNUP:
                        control = "untested"
                    elif await self._accepts_invented_email(client, check, clean_email):
                        continue
                    else:
                        control = "passed"

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
                                "negative_control": control,
                            },
                        )
                    )

        return findings

    @staticmethod
    def _invented_email(email: str) -> str:
        """Correo del mismo dominio que nadie ha registrado."""
        domain = email.rsplit("@", 1)[1]
        alphabet = string.ascii_lowercase + string.digits
        return f"pm{''.join(secrets.choice(alphabet) for _ in range(16))}@{domain}"

    async def _accepts_invented_email(
        self,
        client: httpx.AsyncClient,
        check: Callable[[httpx.AsyncClient, str], Awaitable[Optional[Dict[str, Any]]]],
        email: str,
    ) -> bool:
        """
        Control negativo: ¿la plataforma también da por registrado un correo inventado?

        Una cuenta registrada con el correo de la persona se le atribuye al 99 %,
        así que un falso "registrado" es lo peor que puede enseñarse: una cuenta
        que no existe, presentada como suya. Un correo de prueba sintético
        (`test_student_osint@gmail.com`) llegó a salir registrado en Quora; un
        endpoint que responde "registrado" a cualquier correo lo hace también con
        uno inventado, y así se descubre.
        """
        try:
            res = await check(client, self._invented_email(email))
        except Exception:
            return False
        return isinstance(res, dict) and bool(res.get("registered"))

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

