from typing import List
from app.tools.base import TargetContext, ToolFinding


def extract_and_apply_pivots(findings: List[ToolFinding], context: TargetContext) -> bool:
    """
    Analyzes new findings to extract fresh pivot points (new emails, usernames,
    candidate URLs) and updates context. Returns True if new data was found.
    """
    pivoted = False
    candidate_urls = list(context.extra.get("candidate_urls", []))

    for f in findings:
        metadata = f.metadata_info or {}

        # 1. New emails discovered
        found_emails = metadata.get("emails", []) + metadata.get("extracted_emails", [])
        for em in found_emails:
            em_clean = em.strip().lower()
            if em_clean and em_clean not in context.all_emails():
                context.discovered_emails.append(em_clean)
                pivoted = True

        # 2. New usernames discovered
        found_users = metadata.get("usernames", []) + metadata.get("extracted_usernames", [])
        for u in found_users:
            u_clean = u.strip()
            if u_clean and u_clean not in context.all_usernames():
                context.discovered_usernames.append(u_clean)
                pivoted = True

        # 3. Candidate profile URLs to be verified by social_verifier
        if f.entity_type in ["social_account", "search_mention"] and f.value.startswith("http"):
            if f.value not in candidate_urls:
                candidate_urls.append(f.value)
                pivoted = True

        for link in metadata.get("linked_profiles", []):
            if link and link.startswith("http") and link not in candidate_urls:
                candidate_urls.append(link)
                pivoted = True

    context.extra["candidate_urls"] = candidate_urls
    return pivoted
