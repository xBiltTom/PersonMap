"""Client-reported public evidence, kept distinct from server-collected observations."""
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.workspace import NoteCreate
from app.tools.search_dorker import _bounded_match


class ReportedIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["name", "username", "email", "university", "program", "document_identifier"]
    value: str = Field(min_length=1, max_length=255)


class ExternalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    entity_type: Literal["document", "web_page", "social_account", "search_mention"]
    url: str = Field(max_length=2048)
    source_url: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=255)
    acquisition_method: Literal["agent_browser", "agent_search"]
    evidence_level: Literal["page_content", "search_result"]
    observed_at: datetime
    excerpt: str = Field(min_length=1, max_length=4000)
    locator: str | None = Field(default=None, max_length=500)
    query: str | None = Field(default=None, max_length=1000)
    identifiers: list[ReportedIdentifier] = Field(default_factory=list, max_length=10)
    observed_links: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("url", "source_url")
    @classmethod
    def public_url(cls, value):
        return NoteCreate.public_urls([value])[0]

    _links = field_validator("observed_links")(NoteCreate.public_urls.__func__)

    @field_validator("observed_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at requiere zona horaria")
        if value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("La fecha de observación no puede estar en el futuro")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def grounded_report(self):
        if (self.acquisition_method == "agent_browser") != (self.evidence_level == "page_content"):
            raise ValueError("agent_browser declara contenido de página; agent_search declara resultado de búsqueda")
        if self.url != self.source_url and self.url not in self.excerpt:
            raise ValueError("Cuando el recurso difiere de la fuente, su URL debe aparecer en el extracto")
        if self.evidence_level == "search_result" and (self.identifiers or self.observed_links):
            raise ValueError("Una mención del buscador no introduce identificadores ni enlaces como hechos de página")
        text = re.sub(r"[,;:]", " ", self.excerpt)
        for identifier in self.identifiers:
            if not _bounded_match(identifier.value, text):
                raise ValueError("Cada identificador declarado debe aparecer completo en el extracto")
        for link in self.observed_links:
            if link not in self.excerpt:
                raise ValueError("Los enlaces declarados deben estar presentes en el extracto")
        return self


class ExternalEvidenceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    rationale: str = Field(min_length=1, max_length=1000)
    source_entity_ids: list[UUID] = Field(default_factory=list, max_length=30)
    records: list[ExternalEvidence] = Field(min_length=1, max_length=10)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded_payload(self):
        if len(json.dumps(self.model_dump(mode="json"))) > 80000:
            raise ValueError("El lote de evidencia supera el límite de 80 000 caracteres")
        serialized = [json.dumps(record.model_dump(mode="json"), sort_keys=True) for record in self.records]
        if len(set(serialized)) != len(serialized):
            raise ValueError("El lote contiene observaciones idénticas")
        return self
