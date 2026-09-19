"""
Tests del módulo de persistencia compartido por el motor heurístico y el agente.

Son puramente en memoria: construyen objetos `Entity` sin sesión de base de
datos, de modo que la suite rápida los ejecuta sin PostgreSQL ni red.
"""

import uuid

import pytest

from app.engine.persistence import (
    MAX_EDGES_PER_ENTITY,
    dedupe_findings,
    detect_relationships,
    persist_findings,
)
from app.models.entity import Entity
from app.tools.base import ToolFinding


def _entity(
    *,
    entity_type: str = "social_account",
    platform: str | None = "github",
    value: str = "https://github.com/jperez",
    metadata: dict | None = None,
    source_tool: str = "social_verifier",
) -> Entity:
    return Entity(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        entity_type=entity_type,
        platform=platform,
        value=value,
        display_name=value,
        metadata_info=metadata or {},
        source_tool=source_tool,
    )


# --- Deduplicación -------------------------------------------------------


def test_dedupe_collapses_cosmetic_url_variants():
    """La barra final y las mayúsculas no deben producir entidades duplicadas."""
    findings = [
        ToolFinding(
            entity_type="social_account",
            platform="GitHub",
            value="https://github.com/jperez",
            confidence=0.70,
        ),
        ToolFinding(
            entity_type="social_account",
            platform="github",
            value="https://github.com/jperez/",
            confidence=0.90,
        ),
    ]

    result = dedupe_findings(findings)

    assert len(result) == 1
    # Se conserva el hallazgo de mayor confianza.
    assert result[0].confidence == 0.90


def test_dedupe_keeps_distinct_entity_types():
    findings = [
        ToolFinding(entity_type="email", platform=None, value="a@b.com", confidence=0.9),
        ToolFinding(entity_type="breach", platform=None, value="a@b.com", confidence=0.9),
    ]
    assert len(dedupe_findings(findings)) == 2


def test_dedupe_merges_a_profile_each_tool_names_differently():
    """
    Caso real: `github_deep_scanner` llama "github" al perfil y `username_finder`
    "GitHub (User)". Con la plataforma en la clave salía dos veces (65 % y 10 %),
    cada copia con la procedencia de una sola herramienta.
    """
    findings = [
        ToolFinding(
            entity_type="social_account",
            platform="GitHub (User)",
            value="https://github.com/JorgeWueder",
            confidence=0.90,
            metadata_info={"source_tool": "username_finder"},
        ),
        ToolFinding(
            entity_type="social_account",
            platform="github",
            value="https://www.github.com/JorgeWueder/",
            confidence=0.95,
            metadata_info={"source_tool": "github_deep_scanner"},
        ),
    ]

    result = dedupe_findings(findings)

    assert len(result) == 1
    assert result[0].platform == "github"
    assert result[0].metadata_info["source_tools"] == [
        "username_finder",
        "github_deep_scanner",
    ]


class _MemorySession:
    """Doble mínimo para verificar qué llega a Entity sin PostgreSQL."""

    def __init__(self):
        self.added = []

    def add(self, entity):
        self.added.append(entity)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_persistence_keeps_tool_evidence_urls_for_the_inspector():
    finding = ToolFinding(
        entity_type="social_account",
        platform="github",
        value="https://github.com/jperez",
        confidence=0.9,
        evidence_urls=[
            "https://github.com/jperez",
            "https://github.com/jperez/commits/main",
            "https://github.com/jperez",
        ],
    )

    session = _MemorySession()
    entities = await persist_findings(str(uuid.uuid4()), [finding], None, session)

    assert len(entities) == 1
    assert entities[0].metadata_info["evidence_urls"] == [
        "https://github.com/jperez",
        "https://github.com/jperez/commits/main",
    ]


# --- Detección de relaciones --------------------------------------------


def test_same_platform_no_longer_creates_edges():
    """
    El antiguo caso de reserva `a.platform == b.platform` enlazaba cualquier par
    de la misma red -- e incluso los dos con plataforma None -- sin aportar
    ninguna evidencia.
    """
    a = _entity(platform="twitter", value="https://x.com/ana")
    b = _entity(platform="twitter", value="https://x.com/beto")
    assert detect_relationships(a, b) == []

    sin_plataforma_a = _entity(platform=None, value="dato-a")
    sin_plataforma_b = _entity(platform=None, value="dato-b")
    assert detect_relationships(sin_plataforma_a, sin_plataforma_b) == []


def test_same_username_between_independent_findings_is_an_edge():
    a = _entity(platform="github", metadata={"username": "jperez"}, source_tool="social_verifier")
    b = _entity(platform="keybase", metadata={"username": "JPerez"}, source_tool="keybase_resolver")

    assert detect_relationships(a, b) == [
        ("same_username", False, {"username": "jperez"})
    ]


def test_same_username_between_enumeration_siblings_is_not_an_edge():
    """
    Si `username_finder` busca un alias en cientos de plataformas, todos sus
    hallazgos comparten ese alias por construcción. Enlazarlos entre sí genera
    n*(n-1)/2 aristas tautológicas que vuelven ilegible el mapa: con 91 perfiles
    eran 3.741 aristas sin ninguna información.
    """
    a = _entity(platform="reddit", metadata={"username": "jperez"}, source_tool="username_finder")
    b = _entity(platform="steam", metadata={"username": "jperez"}, source_tool="username_finder")

    assert detect_relationships(a, b) == []


def test_enumeration_sibling_check_handles_agent_prefix():
    """El agente autónomo prefija el source_tool con `agent:`."""
    a = _entity(platform="reddit", metadata={"username": "jperez"}, source_tool="agent:username_finder")
    b = _entity(platform="steam", metadata={"username": "jperez"}, source_tool="agent:username_finder")

    assert detect_relationships(a, b) == []


def test_uses_email_is_detected_in_both_directions():
    """
    El emparejamiento visita cada par una sola vez y el orden de la lista es
    arbitrario, así que la regla debe funcionar sea cual sea el sentido.
    """
    email = _entity(entity_type="email", platform=None, value="jperez@uni.edu.pe")
    profile = _entity(metadata={"emails": ["JPerez@uni.edu.pe"]})

    assert detect_relationships(email, profile) == [
        ("shares_declared_email", True, {"email": "jperez@uni.edu.pe"})
    ]
    assert detect_relationships(profile, email) == [
        ("shares_declared_email", True, {"email": "jperez@uni.edu.pe"})
    ]


def test_linked_to_is_detected_in_both_directions():
    target = _entity(platform="instagram", value="https://instagram.com/jperez")
    profile = _entity(
        platform="github",
        value="https://github.com/jperez",
        metadata={"linked_profiles": ["https://instagram.com/jperez"]},
    )

    assert detect_relationships(profile, target) == [
        ("explicit_profile_link", True, {"linked_profile": "https://instagram.com/jperez"})
    ]
    assert detect_relationships(target, profile) == [
        ("explicit_profile_link", True, {"linked_profile": "https://instagram.com/jperez"})
    ]


def test_malformed_metadata_does_not_raise():
    """Las tools son heterogéneas; los campos de lista pueden llegar con otro tipo."""
    a = _entity(entity_type="email", platform=None, value="x@y.com")
    b = _entity(metadata={"emails": "no-es-una-lista", "linked_profiles": None})

    assert detect_relationships(a, b) == []


def test_edge_budget_constant_is_sane():
    assert 1 <= MAX_EDGES_PER_ENTITY <= 50
