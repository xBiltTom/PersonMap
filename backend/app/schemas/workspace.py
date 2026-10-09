"""Typed MCP/REST contracts shared by the workspace service."""
import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.tools.dni_public import public_source_url


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client: str = Field(min_length=1, max_length=100)
    model: str | None = Field(default=None, max_length=200)


class SessionRead(SessionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    investigation_id: UUID
    status: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["comment", "summary", "insight", "hypothesis", "next_step"] = "comment"
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    evidence_urls: list[str] = Field(default_factory=list, max_length=30)
    entity_ids: list[UUID] = Field(default_factory=list, max_length=100)
    execution_ids: list[UUID] = Field(default_factory=list, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_urls")
    @classmethod
    def public_urls(cls, values):
        result = []
        for value in values:
            url = public_source_url(value)
            if not url or len(url) > 2048:
                raise ValueError("Las fuentes deben ser URLs públicas HTTP(S).")
            if url not in result:
                result.append(url)
        return result

    @field_validator("details")
    @classmethod
    def bounded_json(cls, value):
        if len(json.dumps(value, allow_nan=False)) > 20000:
            raise ValueError("Los detalles del análisis superan el límite de 20 000 caracteres.")
        return value


class NoteRead(NoteCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    investigation_id: UUID
    session_id: UUID | None = None
    author: str
    author_type: str
    created_at: datetime


class SearchQuery(BaseModel):
    """Agent-authored query with literal evidence anchors and explicit domain filters."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=3, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
    include_domains: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("query")
    @classmethod
    def literal_anchor(cls, value):
        if any(ord(char) < 32 for char in value) or value.count('"') % 2:
            raise ValueError("La consulta debe tener comillas equilibradas y una sola línea.")
        if not any(term.strip() for term in re.findall(r'"([^"]+)"', value)):
            raise ValueError('Incluye al menos un término literal entre comillas, por ejemplo "alias".')
        if re.search(r"\bsite:", value, re.IGNORECASE):
            raise ValueError("Usa include_domains para filtrar dominios.")
        return value

    @field_validator("include_domains")
    @classmethod
    def domains(cls, values):
        result = []
        for value in values:
            domain = value.lower().rstrip(".").encode("idna").decode("ascii")
            if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain) or not public_source_url("https://" + domain):
                raise ValueError("Usa dominios públicos, sin esquema, ruta ni operadores.")
            if domain not in result:
                result.append(domain)
        return result


class ToolInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    username: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    dni: str | None = Field(default=None, pattern=r"^[0-9]{8}$")
    university: str | None = Field(default=None, max_length=255)
    candidate_urls: list[str] = Field(default_factory=list, max_length=30)
    queries: list[SearchQuery] = Field(default_factory=list, max_length=5)
    scan_mode: Literal["fast", "deep"] | None = None
    _public_urls = field_validator("candidate_urls")(NoteCreate.public_urls.__func__)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tool_name: str = Field(min_length=1, max_length=100)
    inputs: ToolInputs = Field(default_factory=ToolInputs)
    rationale: str = Field(default="", max_length=1000)
    source_entity_ids: list[UUID] = Field(default_factory=list, max_length=30)
    force: bool = False
