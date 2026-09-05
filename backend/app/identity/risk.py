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

    # 5. Data Breaches / Credential Leaks (Critical)
    breach_entities = [e for e in entities if e.entity_type == "breach"]
    if breach_entities:
        total_breaches = sum(len(e.metadata_info.get("breaches", [])) for e in breach_entities)
        score += min(25 + (total_breaches * 5), 45)

    # 6. Phone number exposure
    phone_count = sum(1 for e in entities if e.entity_type == "phone")
    if phone_count > 0:
        score += 15

    # 7. Perfil académico de autor (Scholar, OpenAlex, ORCID).
    #    Distinto de `academic`: no es una publicación suelta sino un perfil que
    #    agrega toda la producción, la afiliación y la red de coautores.
    academic_profile_count = sum(1 for e in entities if e.entity_type == "academic_profile")
    score += min(academic_profile_count * 6, 12)

    # 8. Cuenta del ecosistema Google confirmada. Es un eje de correlación
    #    especialmente rico: enlaza correo, YouTube, Drive y Scholar bajo una
    #    misma identidad, y es la puerta de entrada a la recuperación de cuentas.
    google_count = sum(1 for e in entities if e.entity_type == "google_account")
    if google_count > 0:
        score += 12

    # 9. Reutilización de la foto de perfil en la web abierta. Permite
    #    correlacionar cuentas que no comparten ni alias ni correo.
    image_match_count = sum(1 for e in entities if e.entity_type == "image_match")
    score += min(image_match_count * 5, 15)

    # 10. Credenciales robadas por malware. Más grave que una filtración de
    #     terceros: implica un equipo comprometido y credenciales en claro.
    infostealer_entities = [e for e in entities if e.entity_type == "infostealer"]
    if infostealer_entities:
        score += 50

    # 11. Cuentas en plataformas de contenido adulto.
    #
    #     Se puntúan alto y aparte, no por juicio moral sino porque el riesgo es
    #     de otra naturaleza: una cuenta así, vinculable por alias reutilizado a
    #     la identidad profesional o académica de alguien, es el material con el
    #     que se hace extorsión. Es además el hallazgo que más rápido convence a
    #     un estudiante de que reutilizar el alias tiene consecuencias.
    sensitive_entities = [e for e in entities if e.entity_type == "sensitive_account"]
    score += min(len(sensitive_entities) * 12, 30)

    # 12. Infraestructura personal (dominios y subdominios propios).
    domain_count = sum(1 for e in entities if e.entity_type == "domain")
    score += min(domain_count * 4, 12)

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

    # Se emiten en orden de gravedad: el infostealer va primero porque implica
    # un equipo comprometido, no solo un servicio de terceros filtrado.
    if infostealer_entities:
        stolen_services = sum(
            int(e.metadata_info.get("total_user_services", 0) or 0)
            for e in infostealer_entities
        )
        machines = ", ".join(
            str(e.metadata_info.get("computer_name"))
            for e in infostealer_entities
            if e.metadata_info.get("computer_name")
        )
        recommendations.append({
            "title": "Credenciales Robadas por Malware (Infostealer)",
            "category": "Equipo Comprometido",
            "impact": "Crítico",
            "description": (
                "Tus credenciales aparecen en registros de malware tipo infostealer"
                + (f" extraídos del equipo {machines}" if machines else "")
                + ". A diferencia de una filtración, aquí el atacante obtuvo las contraseñas "
                "guardadas en el navegador **en texto claro**, junto con cookies de sesión que "
                "permiten saltarse incluso el segundo factor"
                + (f". Se vieron afectados unos {stolen_services} servicios" if stolen_services else "")
                + "."
            ),
            "advice": (
                "Asume que TODAS las contraseñas guardadas en ese equipo están comprometidas: "
                "cámbialas desde un dispositivo limpio, cierra todas las sesiones activas de cada "
                "servicio (no basta con cambiar la clave, la cookie robada sigue siendo válida) y "
                "analiza el equipo con un antimalware antes de volver a usarlo."
            ),
        })

    if sensitive_entities:
        plataformas = ", ".join(
            sorted({str(e.platform) for e in sensitive_entities if e.platform})[:4]
        )
        alias = sorted({
            str((e.metadata_info or {}).get("username"))
            for e in sensitive_entities
            if (e.metadata_info or {}).get("username")
        })
        recommendations.append({
            "title": "Cuentas en Plataformas de Contenido Adulto Vinculables a tu Identidad",
            "category": "Riesgo de Extorsión (Sextorsión)",
            "impact": "Crítico",
            "description": (
                f"Se localizaron {len(sensitive_entities)} perfil(es) en plataformas de "
                f"contenido adulto ({plataformas}) registrados con "
                + (f"el alias '{alias[0]}'" if alias else "un alias")
                + " que también usas en tus perfiles públicos. **El problema no es la "
                "cuenta: es que sea vinculable.** Cualquiera que conozca tu alias "
                "profesional puede llegar hasta aquí en un solo paso, y eso es "
                "exactamente el material con el que se construye una extorsión."
            ),
            "advice": (
                "Usa un alias único e irrepetible para cualquier cuenta que no quieras "
                "ver asociada a tu nombre: no una variante del habitual, uno sin "
                "relación. Comprueba también el correo con el que se registró, porque "
                "vincula igual que el alias. Si alguno de estos perfiles ya no lo usas, "
                "elimínalo en vez de abandonarlo: seguirá siendo localizable."
            ),
        })

    if breach_entities:
        all_breaches_list = []
        for be in breach_entities:
            all_breaches_list.extend(be.metadata_info.get("breaches", []))
        sample_breaches = ", ".join(all_breaches_list[:4])
        recommendations.append({
            "title": "Aparición en Brechas de Seguridad (Data Leaks)",
            "category": "Filtración de Credenciales",
            "impact": "Crítico",
            "description": (
                f"Tu correo electrónico figura en filtraciones públicas masivas ({sample_breaches or 'Múltiples servicios'}). "
                "Ciberdelincuentes poseen copias de hashes de contraseñas, nombres y teléfonos asociados a esta cuenta."
            ),
            "advice": "Cambia inmediatamente las contraseñas en los servicios afectados, activa autenticación de dos factores (2FA) con app (no SMS) y no reutilices claves.",
        })

    if phone_count > 0:
        recommendations.append({
            "title": "Teléfono Móvil Rastreado en Fuentes Abiertas",
            "category": "Ingeniería Social / Smishing",
            "impact": "Alto",
            "description": (
                "Tu número de teléfono está indexado y vinculado a tu identidad digital pública. "
                "Esto abre la puerta a ataques de vishing (llamadas fraudulentas suplantando al banco o la universidad) y SIM swapping."
            ),
            "advice": "Configura la privacidad de WhatsApp y Telegram para que solo tus contactos puedan ver tu foto, biografía y última conexión.",
        })

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

    if google_count > 0:
        recommendations.append({
            "title": "Cuenta Google como Eje de tu Identidad",
            "category": "Concentración de Riesgo",
            "impact": "Alto",
            "description": (
                "Se confirmó una cuenta activa del ecosistema Google asociada a tu identidad. "
                "Una sola cuenta enlaza correo, YouTube, Drive, Maps y producción académica: "
                "quien la comprometa obtiene además la recuperación de casi todas las demás."
            ),
            "advice": (
                "Activa la Verificación en 2 Pasos con clave de acceso o app autenticadora (no SMS), "
                "revisa en myaccount.google.com/permissions qué aplicaciones de terceros tienen acceso, "
                "y comprueba que tus reseñas de Maps y listas de YouTube no sean públicas."
            ),
        })

    if image_match_count > 0:
        recommendations.append({
            "title": "Foto de Perfil Reutilizada en Varias Plataformas",
            "category": "Correlación Visual",
            "impact": "Alto",
            "description": (
                f"Tu imagen de perfil aparece en {image_match_count} ubicación(es) distintas de la web pública. "
                "Reutilizar la misma foto permite enlazar cuentas que no comparten ni alias ni correo: "
                "es la técnica de correlación más difícil de evitar una vez publicada."
            ),
            "advice": (
                "Usa imágenes distintas (y sin metadatos EXIF) para tus perfiles profesionales y personales. "
                "Recuerda que una foto ya indexada no se puede retirar de las cachés de terceros."
            ),
        })

    if academic_profile_count > 0:
        recommendations.append({
            "title": "Perfil de Autor Académico Público",
            "category": "OSINT Académico",
            "impact": "Medio",
            "description": (
                "Tienes un perfil de autor indexado que agrega tu producción, afiliación institucional "
                "y red de coautores. Es legítimo y deseable para tu carrera, pero también revela "
                "tu ubicación institucional y tu círculo profesional a cualquiera."
            ),
            "advice": (
                "Revisa qué datos de contacto expone tu perfil público y evita que aparezca ahí tu "
                "correo personal o tu teléfono; deja únicamente el institucional."
            ),
        })

    if domain_count > 0:
        recommendations.append({
            "title": "Dominio Personal Registrado a tu Nombre",
            "category": "Infraestructura Expuesta",
            "impact": "Medio",
            "description": (
                "Se detectaron dominios o subdominios atribuibles a ti. Los registros WHOIS y los "
                "certificados de transparencia son públicos por diseño y pueden exponer tu nombre, "
                "correo y a veces tu dirección postal."
            ),
            "advice": (
                "Activa la protección de privacidad WHOIS en tu registrador y evita nombrar "
                "subdominios internos (dev, admin, backup) en certificados públicos."
            ),
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
