from datetime import datetime, timezone
from typing import Any, Dict, List
from app.agent.llm_client import llm_client
from app.models.entity import Entity
from app.models.target import Target


class OSINTAgent:
    """
    AI OSINT Agent that synthesizes correlations, reasons about target descriptions,
    and produces deep pedagogical awareness narratives.
    """

    async def generate_intelligence_narrative(
        self,
        target: Target,
        entities: List[Entity],
        risk_score: int,
        risk_level: str,
    ) -> str:
        if not llm_client.enabled:
            return self._fallback_template(target, entities, risk_score, risk_level)

        prompt_entities = [
            f"- [{e.entity_type.upper()}] {e.platform or 'web'}: {e.display_name or e.value} (Certeza: {int(e.confidence*100)}%)"
            for e in entities[:20]
        ]

        messages = [
            {
                "role": "system",
                "content": (
                    "Eres un analista de ciberinteligencia (OSINT) y experto en concientización de seguridad digital para estudiantes. "
                    "Tu objetivo es explicar cómo los datos públicos dispersos de una persona pueden correlacionarse para reconstruir su identidad, "
                    "los riesgos de ingeniería social o doxxing que enfrenta, y cómo mitigar dicha exposición. "
                    "Sé riguroso, analítico y formativo (estilo Palantir Intelligence Report).\n\n"
                    "REGLAS ESTRICTAS:\n"
                    "- No inventes NINGÚN dato que no esté en los hallazgos entregados. Este "
                    "informe se le enseña a la persona investigada: un dato falso destruye la "
                    "credibilidad de todo lo demás.\n"
                    "- No escribas fechas de tu cosecha. La fecha del análisis se te da y es la "
                    "única válida.\n"
                    "- Formato Markdown simple: `##` para las secciones, `**negrita**` para lo "
                    "destacado y `-` para las listas. Nada de HTML ni de tablas."
                ),
            },
            {
                "role": "user",
                "content": (
                    # La fecha se inyecta porque el modelo se la inventaba: el
                    # informe salía fechado dos años atrás. Mostrado a la persona
                    # investigada, un dato así tira por tierra la credibilidad
                    # del resto del expediente.
                    f"Fecha del análisis (usa EXACTAMENTE esta): "
                    f"{datetime.now(timezone.utc).strftime('%d/%m/%Y')}\n"
                    f"Objetivo de la investigación: {target.full_name or target.username or target.email}\n"
                    f"Correo: {target.email or 'No proporcionado'}\n"
                    f"Universidad: {target.university or 'No especificada'}\n"
                    f"Contexto/Descripción ingresada: {target.description or 'Ninguna'}\n"
                    f"Nivel de Exposición Calculado: {risk_score}/100 ({risk_level})\n\n"
                    f"Hallazgos públicos comprobados:\n" + "\n".join(prompt_entities) + "\n\n"
                    "Genera un informe ejecutivo conciso estructurado en:\n"
                    "1. Resumen de Reconstrucción de Identidad\n"
                    "2. Vectores de Riesgo Identificados (Spear-phishing, correlación cruzada, etc.)\n"
                    "3. Recomendaciones Pedagógicas Clave"
                ),
            },
        ]

        response = await llm_client.generate_completion(messages, temperature=0.3)
        return response or self._fallback_template(target, entities, risk_score, risk_level)

    def _fallback_template(
        self,
        target: Target,
        entities: List[Entity],
        risk_score: int,
        risk_level: str,
    ) -> str:
        social_count = sum(1 for e in entities if e.entity_type == "social_account")
        academic_count = sum(1 for e in entities if e.entity_type == "academic")
        email_count = sum(1 for e in entities if e.entity_type == "email")

        return (
            f"### Informe Ejecutivo de Huella Digital\n\n"
            f"**Objetivo:** {target.full_name or target.username or target.email}\n"
            f"**Nivel de Exposición:** {risk_score}/100 — Riesgo {risk_level}\n\n"
            f"El motor de correlación identificó un total de **{len(entities)} entidades públicas**:\n"
            f"- **{social_count}** cuentas en redes y plataformas sociales/desarrollo.\n"
            f"- **{academic_count}** registros de índole académica (papers, autorías o repositorios).\n"
            f"- **{email_count}** direcciones de correo vinculadas.\n\n"
            f"#### Análisis de Correlación:\n"
            f"A partir de los identificadores iniciales, se comprobó la reutilización de alias y la persistencia de nombres visibles "
            f"a través de diferentes ecosistemas. Esto permite a un observador externo perfilar la carrera, horarios y círculos del estudiante."
        )


osint_agent = OSINTAgent()
