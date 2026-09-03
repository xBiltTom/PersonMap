from typing import Any, Dict, List, Optional
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class KeybaseResolverTool(BaseTool):
    """
    Keybase Identity Resolution Tool adapted from Spiderfoot's sfp_keybase.
    Resolves usernames into cryptographically verified identity links across
    Twitter, GitHub, Reddit, Hackernews, websites, and PGP keys (zero API key needed).
    """

    name = "keybase_resolver"
    description = "Resolución de identidad verificada criptográficamente via Keybase (Twitter, GitHub, Reddit, PGP)"
    category = ToolCategory.SOCIAL
    required_inputs = ["username"]

    API_URL = "https://keybase.io/_/api/1.0/user/lookup.json"

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        usernames = context.all_usernames()
        if not usernames:
            return findings

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers, verify=False) as client:
            for username in usernames:
                clean_user = username.strip()
                if len(clean_user) < 3:
                    continue

                try:
                    resp = await client.get(self.API_URL, params={"usernames": clean_user})
                    if resp.status_code != 200:
                        continue

                    content = resp.json()
                    if content.get("status", {}).get("code") != 0:
                        continue

                    users = content.get("them", [])
                    if not users or not isinstance(users, list):
                        continue

                    for user in users:
                        if not user or not isinstance(user, dict):
                            continue

                        basics = user.get("basics", {})
                        kb_username = basics.get("username", clean_user)
                        profile = user.get("profile", {})
                        full_name = profile.get("full_name")
                        location = profile.get("location")
                        bio = profile.get("bio")

                        # 1. Main Keybase Identity
                        kb_url = f"https://keybase.io/{kb_username}"
                        findings.append(
                            ToolFinding(
                                entity_type="social_account",
                                platform="keybase",
                                value=kb_url,
                                display_name=f"Keybase: @{kb_username} ({full_name or 'Verificado'})",
                                confidence=0.99,
                                metadata_info={
                                    "source_tool": "keybase_resolver",
                                    "username": kb_username,
                                    "full_name": full_name,
                                    "location": location,
                                    "bio": bio,
                                    "url": kb_url,
                                    "cryptographically_verified": True,
                                },
                            )
                        )

                        # 2. Cryptographically Proven External Links
                        proofs = user.get("proofs_summary", {}).get("all", [])
                        extracted_users = []
                        for proof in proofs:
                            proof_type = proof.get("proof_type", "social")
                            nametag = proof.get("nametag")
                            service_url = proof.get("service_url")

                            if nametag:
                                extracted_users.append(nametag)

                            if service_url:
                                findings.append(
                                    ToolFinding(
                                        entity_type="social_account",
                                        platform=proof_type,
                                        value=service_url,
                                        display_name=f"{proof_type.capitalize()}: @{nametag or 'user'} (Keybase Proof)",
                                        confidence=0.99,  # Cryptographically verified link
                                        metadata_info={
                                            "source_tool": "keybase_resolver",
                                            "platform": proof_type,
                                            "username": nametag,
                                            "url": service_url,
                                            "cryptographically_proven": True,
                                            "proof_id": proof.get("proof_id"),
                                            "usernames": [nametag] if nametag else [],
                                        },
                                    )
                                )

                        # 3. PGP Key & Crypto Addresses
                        primary_key = user.get("public_keys", {}).get("primary", {})
                        key_fp = primary_key.get("key_fingerprint")
                        if key_fp:
                            findings.append(
                                ToolFinding(
                                    entity_type="search_mention",
                                    platform="keybase_pgp",
                                    value=f"PGP:{key_fp}",
                                    display_name=f"PGP Key: {key_fp[-16:]}",
                                    confidence=0.99,
                                    metadata_info={
                                        "source_tool": "keybase_resolver",
                                        "fingerprint": key_fp,
                                        "key_id": primary_key.get("key_id"),
                                    },
                                )
                            )

                except Exception:
                    continue

        return findings
