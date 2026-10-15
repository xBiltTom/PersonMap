import re
from typing import List, Optional
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.email_enumerator import valid_email

ENGINE_VERSION = 2


class EmailCheckerTool(BaseTool):
    """
    Email Infrastructure & Domain Intelligence Tool.
    Classifies email addresses into Academic, Corporate, Disposable (burner), or Free providers,
    extracts inferred human names from email formats (e.g. juan.perez@ -> Juan Perez),
    and queries GitHub's public email attribution index.
    """

    name = "email_checker"
    description = "Análisis de infraestructura de correo (clasificación académica/desechable, extracción de nombres y atribución Git)"
    category = ToolCategory.EMAIL
    required_inputs = ["email", "discovered_emails"]
    cache_prefix = "email_checker_"

    def pending(self, context):
        checked = context.extra.get("email_checker_checked", []) if context.extra.get("email_checker_version") == ENGINE_VERSION else []
        emails = [value for value in context.all_emails() if valid_email(value)]
        admitted = list(dict.fromkeys([*checked, *emails]))[:3]
        return [email for email in emails if email in admitted and email not in checked]

    def can_run(self, context):
        return bool(self.pending(context))

    ACADEMIC_PATTERNS = [
        ".edu", ".ac.", ".edu.", "uni.edu.pe", "unmsm.edu.pe", "pucp.edu.pe",
        "utp.edu.pe", "upc.edu.pe", "usmp.pe", "ulima.edu.pe", "unt.edu.pe",
        "unsa.edu.pe", "unsaac.edu.pe", "unfv.edu.pe", "lamolina.edu.pe",
        "upn.pe", "ucv.edu.pe", "cientifica.edu.pe", "continental.edu.pe",
    ]

    FREE_PROVIDERS = {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
        "yahoo.com", "icloud.com", "proton.me", "protonmail.com", "aol.com",
        "zoho.com", "yandex.com", "mail.com",
    }

    DISPOSABLE_PROVIDERS = {
        "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
        "throwawaymail.com", "yopmail.com", "trashmail.com", "getairmail.com",
        "dispostable.com", "sharklasers.com", "temp-mail.org",
    }

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if context.extra.get("email_checker_version") != ENGINE_VERSION:
            context.extra.update(email_checker_version=ENGINE_VERSION, email_checker_checked=[], email_checker_diagnostics={})
        emails = self.pending(context)
        if not emails:
            return []

        findings: List[ToolFinding] = []

        async with http_client.build_client(timeout=8.0, public_only=True, follow_redirects=False,
                                            max_retries=0, trust_env=False) as client:
            for email in emails:
                context.extra["email_checker_checked"].append(email)
                clean_email = email.strip().lower()
                if "@" not in clean_email:
                    continue

                username_part, domain_part = clean_email.split("@", 1)

                # 1. Classify domain type
                is_academic = any(pat in domain_part for pat in self.ACADEMIC_PATTERNS)
                is_disposable = domain_part in self.DISPOSABLE_PROVIDERS
                is_free = domain_part in self.FREE_PROVIDERS
                provider_type = "academic" if is_academic else ("disposable" if is_disposable else ("free_webmail" if is_free else "corporate"))

                # 2. Heuristic human name extraction from email (Spiderfoot sfp_names style)
                inferred_name: Optional[str] = None
                if "." in username_part and not any(ch.isdigit() for ch in username_part):
                    parts = [p.capitalize() for p in username_part.split(".") if len(p) >= 2]
                    if len(parts) >= 2:
                        inferred_name = " ".join(parts)

                extracted_names = [inferred_name] if inferred_name else []
                extracted_users = [username_part] if len(username_part) >= 3 else []

                # 3. Base Email Entity Finding
                findings.append(
                    ToolFinding(
                        entity_type="email",
                        platform=domain_part,
                        value=clean_email,
                        display_name=f"{clean_email} ({provider_type.upper()})",
                        confidence=1.0,
                        metadata_info={
                            "source_tool": "email_checker",
                            "domain": domain_part,
                            "provider_type": provider_type,
                            "is_academic": is_academic,
                            "is_disposable": is_disposable,
                            "inferred_name": inferred_name,
                            "names": extracted_names,
                            "usernames": extracted_users,
                            "url": f"mailto:{clean_email}",
                        },
                    )
                )

                # Search is discovery only. Confirm an exact public email on
                # each returned profile; a ranked search hit is not a commit.
                diagnostics = context.extra["email_checker_diagnostics"].setdefault(clean_email, {"status": "pending", "requests": 0})
                try:
                    diagnostics["requests"] += 1
                    response = await client.get("https://api.github.com/search/users",
                        params={"q": '"' + clean_email.replace('"', '') + '" in:email', "per_page": 3},
                        headers={"Accept": "application/vnd.github+json"})
                    if response.status_code != 200:
                        diagnostics["status"] = "rate_limited" if response.status_code == 429 else "blocked" if response.status_code in {401, 403} else "upstream_error"
                        diagnostics["http_status"] = response.status_code
                        continue
                    data = response.json()
                    items = data.get("items") if isinstance(data, dict) else None
                    if not isinstance(items, list):
                        diagnostics["status"] = "unexpected_response"
                        continue
                    diagnostics["status"] = "no_public_email_match"
                    for item in items[:3]:
                        login = item.get("login") if isinstance(item, dict) else None
                        if not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
                            continue
                        diagnostics["requests"] += 1
                        profile = await client.get("https://api.github.com/users/" + login,
                                                   headers={"Accept": "application/vnd.github+json"})
                        if profile.status_code != 200:
                            if diagnostics["status"] != "public_email_match":
                                diagnostics["status"] = "profile_unavailable"
                            continue
                        account = profile.json()
                        if (not isinstance(account, dict) or not isinstance(account.get("login"), str) or account["login"].lower() != login.lower()
                                or not isinstance(account.get("email"), str) or account["email"].strip().lower() != clean_email):
                            continue
                        url = "https://github.com/" + login
                        diagnostics["status"] = "public_email_match"
                        findings.append(ToolFinding(entity_type="social_account", platform="github", value=url,
                            display_name="GitHub: @" + login, confidence=0.8, evidence_urls=[str(profile.url)],
                            metadata_info={"source_tool": self.name, "username": login, "url": url,
                                "matched_email": clean_email, "usernames": [login], "verification_status": "verified",
                                "ownership_status": "unverified", "technique": "github_public_profile_email",
                                "association_evidence": "exact_public_profile_email", "avatar_url": account.get("avatar_url")}))
                except Exception as exc:
                    if diagnostics["status"] != "public_email_match":
                        diagnostics.update(status="request_error", error_type=type(exc).__name__)
        return findings
