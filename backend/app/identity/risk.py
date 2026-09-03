from typing import Any, Dict, List, Tuple
from app.models.entity import Entity
from app.models.target import Target


def calculate_risk_score(entities: List[Entity], target: Target) -> Tuple[int, str, List[Dict[str, Any]]]:
    """
    Calculates the Digital Exposure Risk Score (0-100) and returns
    (score, risk_level, recommendations_list).
    """
    score = 10  # Base public presence score

    # 1. Number of confirmed public profiles
    social_count = sum(1 for e in entities if e.entity_type == "social_account" and e.confidence >= 0.60)
    score += min(social_count * 8, 40)

    # 2. Email exposure
    email_entities = [e for e in entities if e.entity_type == "email"]
    for em in email_entities:
        is_academic = em.metadata_info.get("is_academic", False)
        if is_academic:
            score += 15  # Institutional email exposed
        else:
            score += 10  # Personal email exposed

    # 3. Academic papers and institutional trace
    academic_count = sum(1 for e in entities if e.entity_type == "academic")
    score += min(academic_count * 5, 20)

    # 4. Search mentions and cross-links
    dork_count = sum(1 for e in entities if e.entity_type == "search_mention")
    score += min(dork_count * 4, 15)

    # Cap score at 100
    final_score = min(max(score, 5), 100)

    # Risk level classification
    if final_score >= 75:
        level = "CRÍTICO"
    elif final_score >= 50:
        level = "ALTO"
    elif final_score >= 25:
        level = "MEDIO"
    else:
        level = "BAJO"

    # Actionable Awareness Recommendations
    recommendations: List[Dict[str, Any]] = []

    if social_count >= 3:
        recommendations.append({
            "title": "Reutilización de Alias en Múltiples Redes",
            "category": "Privacidad y Rastreo",
            "impact": "Alto",
            "description": (
                f"Se detectó el mismo nombre de usuario en {social_count} plataformas públicas. "
                "Un atacante puede correlacionar tu vida académica, personal y de entretenimiento con solo conocer un alias."
            ),
            "advice": "Utiliza alias independientes para tus cuentas de ocio/videojuegos y perfiles académicos o profesionales.",
        })

    if any(em.metadata_info.get("is_academic") for em in email_entities):
        recommendations.append({
            "title": "Exposición de Correo Institucional",
            "category": "Ingeniería Social / Phishing",
            "impact": "Alto",
            "description": (
                "Tu correo universitario es visible públicamente en servicios externos o repositorios de código. "
                "Esto facilita ataques de phishing dirigido (spear-phishing) suplantando a docentes o autoridades de la facultad."
            ),
            "advice": "No utilices el correo institucional para registrarte en plataformas de redes sociales o servicios no académicos.",
        })

    if academic_count > 0:
        recommendations.append({
            "title": "Huella Académica y Horaria Identificable",
            "category": "OSINT Académico",
            "impact": "Medio",
            "description": (
                "Tus publicaciones, tesis o repositorios de tareas permiten deducir tu carrera, facultad y proyectos actuales."
            ),
            "advice": "Revisa los commits de tus repositorios públicos en GitHub para asegurar que no contengan credenciales o números de teléfono en archivos README o configs.",
        })

    if not recommendations:
        recommendations.append({
            "title": "Huella Digital Controlada",
            "category": "Higiene Digital",
            "impact": "Bajo",
            "description": "Se detectó poca información pública indexada, lo que reduce la superficie de ataque inicial.",
            "advice": "Mantén las configuraciones de privacidad estrictas y audita tus cuentas periódicamente.",
        })

    return final_score, level, recommendations
