import re
from typing import Any, Dict, List, Optional
import httpx
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


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
        emails = context.all_emails()
        if not emails:
            return []

        findings: List[ToolFinding] = []

        async with http_client.build_client(timeout=8.0) as client:
            for email in emails:
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

                # 4. GitHub Email Search API Attribution (unauthenticated public query)
                try:
                    gh_url = f"https://api.github.com/search/users?q={clean_email}+in:email"
                    resp = await http_client.get(client, gh_url, headers={"Accept": "application/json"})
                    if resp is not None and resp.status_code == 200:
                        gh_data = resp.json()
                        if gh_data.get("total_count", 0) > 0:
                            item = gh_data["items"][0]
                            gh_user = item.get("login")
                            gh_profile = item.get("html_url")
                            findings.append(
                                ToolFinding(
                                    entity_type="social_account",
                                    platform="github",
                                    value=gh_profile or f"https://github.com/{gh_user}",
                                    display_name=f"GitHub (Commit Email Match): @{gh_user}",
                                    confidence=0.96,
                                    metadata_info={
                                        "source_tool": "email_checker",
                                        "username": gh_user,
                                        "matched_email": clean_email,
                                        "usernames": [gh_user] if gh_user else [],
                                        "avatar_url": item.get("avatar_url"),
                                    },
                                )
                            )
                except Exception:
                    pass

        return findings
