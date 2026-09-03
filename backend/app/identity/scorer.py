from typing import Any, Dict, Tuple
from thefuzz import fuzz
from app.models.target import Target


SCORING_WEIGHTS = {
    "name_match": 0.30,
    "email_match": 0.25,
    "university_match": 0.20,
    "username_match": 0.15,
    "cross_link": 0.10,
}


def compute_identity_score(
    display_name: str | None,
    value: str,
    metadata: Dict[str, Any],
    target: Target,
) -> Tuple[float, Dict[str, float]]:
    """
    Computes a 0.0 to 1.0 identity confidence score comparing a discovered
    entity against the target profile. Returns (overall_score, breakdown_dict).
    """
    breakdown: Dict[str, float] = {}

    # 1. Full name match
    if target.full_name and (display_name or metadata.get("og_title")):
        check_text = f"{display_name or ''} {metadata.get('og_title', '')} {metadata.get('bio', '')}"
        ratio = fuzz.partial_ratio(target.full_name.lower(), check_text.lower()) / 100.0
        breakdown["name_match"] = ratio
    else:
        breakdown["name_match"] = 0.0

    # 2. Email match / cross-link
    if target.email:
        emails_found = metadata.get("emails", []) + metadata.get("extracted_emails", [])
        if any(target.email.lower() == e.lower() for e in emails_found) or target.email.lower() in value.lower():
            breakdown["email_match"] = 1.0
        else:
            breakdown["email_match"] = 0.0
    else:
        breakdown["email_match"] = 0.0

    # 3. University / Institution match
    if target.university:
        bio = metadata.get("bio", "") or metadata.get("snippet", "")
        institutions = metadata.get("institutions", [])
        combined_uni = f"{bio} {' '.join(institutions)}"
        if target.university.lower() in combined_uni.lower():
            breakdown["university_match"] = 1.0
        else:
            breakdown["university_match"] = 0.0
    else:
        breakdown["university_match"] = 0.0

    # 4. Username match
    if target.username:
        raw_user = target.username.lower()
        if raw_user in value.lower() or (display_name and raw_user in display_name.lower()):
            breakdown["username_match"] = 1.0
        else:
            breakdown["username_match"] = 0.2
    else:
        breakdown["username_match"] = 0.0

    # 5. Cross-linking in profile bio
    links = metadata.get("linked_profiles", []) + metadata.get("extracted_usernames", [])
    if links:
        breakdown["cross_link"] = 0.8
    else:
        breakdown["cross_link"] = 0.0

    # Calculate weighted total
    total_score = sum(
        breakdown[k] * SCORING_WEIGHTS[k]
        for k in SCORING_WEIGHTS
    )

    # Base baseline: If platform exists with matching username, floor is 0.40
    if breakdown.get("username_match", 0) > 0.5:
        total_score = max(total_score, 0.45)

    return round(min(max(total_score, 0.1), 0.99), 2), breakdown
