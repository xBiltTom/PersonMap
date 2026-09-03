import math
from typing import Any, Dict, Tuple
from thefuzz import fuzz
from app.models.target import Target


# Fellegi-Sunter Conditional Probabilities for Person Record Linkage
# m = P(agree | Match): probability attribute agrees given same physical person
# u = P(agree | Non-Match): probability attribute agrees by chance collision
FELLEGI_SUNTER_PARAMS: Dict[str, Dict[str, float]] = {
    "name_match": {"m": 0.92, "u": 0.005},
    "email_match": {"m": 0.98, "u": 0.0002},
    "university_match": {"m": 0.85, "u": 0.04},
    "username_match": {"m": 0.88, "u": 0.008},
    "phone_match": {"m": 0.95, "u": 0.0001},
    "cross_link": {"m": 0.80, "u": 0.01},
    "cryptographic_proof": {"m": 0.999, "u": 0.00001},
}

PRIOR_MATCH_PROBABILITY = 0.02  # Prior probability before observing field matches


def compute_identity_score(
    display_name: str | None,
    value: str,
    metadata: Dict[str, Any],
    target: Target,
) -> Tuple[float, Dict[str, float]]:
    """
    Computes a posterior match probability P(Match | gamma) using the formal
    Fellegi-Sunter probabilistic record linkage framework with log-likelihood weights.
    Returns (posterior_probability, breakdown_dict).
    """
    agreements: Dict[str, float] = {}

    # 1. Full name comparison (continuous fuzzy degree [0.0, 1.0])
    if target.full_name and (display_name or metadata.get("og_title") or metadata.get("name")):
        name_corpus = f"{display_name or ''} {metadata.get('og_title', '')} {metadata.get('name', '')} {metadata.get('bio', '')}"
        ratio = fuzz.partial_ratio(target.full_name.lower(), name_corpus.lower()) / 100.0
        agreements["name_match"] = round(ratio, 2) if ratio >= 0.50 else 0.0
    else:
        agreements["name_match"] = 0.0

    # 2. Email exact match
    if target.email:
        emails_found = [e.lower() for e in (metadata.get("emails", []) + metadata.get("extracted_emails", []))]
        target_em = target.email.lower().strip()
        if target_em in emails_found or target_em in value.lower():
            agreements["email_match"] = 1.0
        else:
            agreements["email_match"] = 0.0
    else:
        agreements["email_match"] = 0.0

    # 3. University / Organization affiliation
    if target.university:
        bio = metadata.get("bio", "") or metadata.get("snippet", "")
        institutions = metadata.get("institutions", [])
        combined_uni = f"{bio} {' '.join(institutions)} {metadata.get('company_university', '')}"
        if target.university.lower() in combined_uni.lower():
            agreements["university_match"] = 1.0
        else:
            agreements["university_match"] = 0.0
    else:
        agreements["university_match"] = 0.0

    # 4. Username match
    if target.username:
        raw_user = target.username.lower().strip()
        found_users = [u.lower() for u in (metadata.get("usernames", []) + [metadata.get("username", "")])]
        if raw_user in found_users or raw_user in value.lower() or (display_name and raw_user in display_name.lower()):
            agreements["username_match"] = 1.0
        else:
            agreements["username_match"] = 0.0
    else:
        agreements["username_match"] = 0.0

    # 5. Phone match
    if target.phone:
        clean_target_phone = "".join(filter(str.isdigit, target.phone))
        phones_found = ["".join(filter(str.isdigit, p)) for p in metadata.get("phones", [])]
        if clean_target_phone in phones_found or clean_target_phone in value:
            agreements["phone_match"] = 1.0
        else:
            agreements["phone_match"] = 0.0
    else:
        agreements["phone_match"] = 0.0

    # 6. Cross-linking / bio mentions
    links = metadata.get("linked_profiles", []) + metadata.get("extracted_usernames", [])
    agreements["cross_link"] = 1.0 if len(links) > 0 else 0.0

    # 7. Cryptographic proof (Keybase)
    agreements["cryptographic_proof"] = 1.0 if metadata.get("cryptographically_proven") else 0.0

    # Fellegi-Sunter Log-Likelihood Calculation
    total_weight = 0.0
    breakdown: Dict[str, float] = {}

    for field, params in FELLEGI_SUNTER_PARAMS.items():
        m, u = params["m"], params["u"]
        gamma = agreements.get(field, 0.0)

        # Weight calculation: positive evidence for agreement, negative for disagreement
        w_plus = math.log2(m / u)
        w_minus = math.log2((1.0 - m) / (1.0 - u))

        # Interpolate for continuous agreement (such as fuzzy name)
        field_weight = w_minus + gamma * (w_plus - w_minus)
        total_weight += field_weight

        # Store standard 0.0-1.0 agreement for backwards compatibility
        breakdown[field] = gamma
        # Store exact Fellegi-Sunter log2 weight for scientific analysis
        breakdown[f"{field}_weight"] = round(field_weight, 2)

    breakdown["log_likelihood_ratio"] = round(total_weight, 2)

    # Convert log-likelihood ratio into posterior probability via odds
    prior_odds = PRIOR_MATCH_PROBABILITY / (1.0 - PRIOR_MATCH_PROBABILITY)
    likelihood_ratio = 2.0 ** total_weight
    posterior_odds = prior_odds * likelihood_ratio
    posterior_probability = posterior_odds / (1.0 + posterior_odds)

    # Baseline adjustment for single exact username vs homonym rejection
    if agreements.get("username_match") == 1.0:
        posterior_probability = max(posterior_probability, 0.45)
    if agreements.get("cryptographic_proof") == 1.0 or agreements.get("email_match") == 1.0:
        posterior_probability = max(posterior_probability, 0.95)

    final_score = round(min(max(posterior_probability, 0.05), 0.99), 2)
    return final_score, breakdown
