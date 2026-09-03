from app.identity.scorer import compute_identity_score
from app.models.target import Target


def test_identity_scoring_high_match():
    target = Target(
        full_name="Carlos Eduardo Mendoza",
        email="cmendoza@untumbes.edu.pe",
        username="cmendoza_dev",
        university="Universidad Nacional de Tumbes",
    )

    display_name = "Carlos Mendoza (@cmendoza_dev)"
    value = "https://github.com/cmendoza_dev"
    metadata = {
        "og_title": "Carlos E. Mendoza",
        "bio": "Estudiante de Ingeniería de Sistemas en Universidad Nacional de Tumbes",
        "emails": ["cmendoza@untumbes.edu.pe"],
        "username": "cmendoza_dev",
    }

    score, breakdown = compute_identity_score(display_name, value, metadata, target)
    assert score >= 0.80
    assert breakdown["name_match"] > 0.70
    assert breakdown["email_match"] == 1.0
    assert breakdown["university_match"] == 1.0


def test_identity_scoring_homonym_low_match():
    target = Target(
        full_name="Carlos Eduardo Mendoza",
        email="cmendoza@untumbes.edu.pe",
        username="cmendoza_dev",
        university="Universidad Nacional de Tumbes",
    )

    # Completely different person in another country with same username
    display_name = "Carlos Müller"
    value = "https://instagram.com/cmendoza_dev"
    metadata = {
        "og_title": "Carlos Müller",
        "bio": "Fotógrafo en Berlín, Alemania. Contact: info@muller-berlin.de",
        "emails": ["info@muller-berlin.de"],
        "username": "cmendoza_dev",
    }

    score, breakdown = compute_identity_score(display_name, value, metadata, target)
    # Score should be lower because email and university don't match
    assert breakdown["email_match"] == 0.0
    assert breakdown["university_match"] == 0.0
    assert score < 0.65
