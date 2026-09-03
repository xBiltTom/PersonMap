import hashlib
from typing import Any, Dict, List, Optional
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class GravatarDeepTool(BaseTool):
    """
    Deep Gravatar Intelligence Module adapted from Spiderfoot's sfp_gravatar.
    Resolves email MD5 hash into verified full name, preferred usernames,
    alternate emails, phone numbers, location, linked social accounts, and avatar URLs.
    """

    name = "gravatar_deep"
    description = "Extracción profunda de identidad Gravatar (nombre real, usernames, teléfonos, emails alternos, enlaces sociales y avatar)"
    category = ToolCategory.EMAIL
    required_inputs = ["email"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        emails = context.all_emails()
        if not emails:
            return findings

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers, verify=False) as client:
            for email in emails:
                clean_email = email.strip().lower()
                md5_hash = hashlib.md5(clean_email.encode("utf-8")).hexdigest()
                url = f"https://en.gravatar.com/{md5_hash}.json"

                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    entries = data.get("entry", [])
                    if not entries:
                        continue

                    entry = entries[0]

                    # 1. Base Profile Identity
                    display_name = entry.get("displayName")
                    formatted_name = entry.get("name", {}).get("formatted")
                    preferred_username = entry.get("preferredUsername")
                    location = entry.get("currentLocation")
                    about_me = entry.get("aboutMe")
                    thumbnail_url = entry.get("thumbnailUrl") or f"https://www.gravatar.com/avatar/{md5_hash}?s=400"

                    extracted_usernames = []
                    if preferred_username:
                        extracted_usernames.append(preferred_username)

                    # Extract alternate emails
                    extracted_emails = []
                    for em in entry.get("emails", []):
                        val = em.get("value")
                        if val and val.lower() != clean_email:
                            extracted_emails.append(val.lower())

                    # Extract phone numbers
                    extracted_phones = []
                    for ph in entry.get("phoneNumbers", []):
                        val = ph.get("value")
                        if val:
                            extracted_phones.append(val)

                    profile_meta: Dict[str, Any] = {
                        "source_tool": "gravatar_deep",
                        "email": clean_email,
                        "display_name": display_name or formatted_name,
                        "preferred_username": preferred_username,
                        "location": location,
                        "bio": about_me,
                        "avatar_url": thumbnail_url,
                        "emails": extracted_emails,
                        "usernames": extracted_usernames,
                        "phones": extracted_phones,
                    }

                    # Add main Gravatar profile entity
                    findings.append(
                        ToolFinding(
                            entity_type="social_account",
                            platform="gravatar",
                            value=f"https://gravatar.com/{preferred_username or md5_hash}",
                            display_name=f"Gravatar: {display_name or formatted_name or clean_email}",
                            confidence=0.98,
                            metadata_info=profile_meta,
                        )
                    )

                    # 2. Linked Social Accounts
                    accounts = entry.get("accounts", [])
                    for acc in accounts:
                        shortname = acc.get("shortname") or acc.get("domain", "social")
                        acc_url = acc.get("url")
                        acc_user = acc.get("username") or acc.get("display")
                        verified = acc.get("verified") == "true" or acc.get("verified") is True

                        if acc_url:
                            findings.append(
                                ToolFinding(
                                    entity_type="social_account",
                                    platform=shortname,
                                    value=acc_url,
                                    display_name=f"{shortname.capitalize()}: @{acc_user or 'usuario'}",
                                    confidence=0.95 if verified else 0.88,
                                    metadata_info={
                                        "source_tool": "gravatar_deep",
                                        "platform": shortname,
                                        "username": acc_user,
                                        "url": acc_url,
                                        "verified_on_gravatar": verified,
                                        "origin_email": clean_email,
                                        "usernames": [acc_user] if acc_user else [],
                                    },
                                )
                            )

                except Exception:
                    continue

        return findings
