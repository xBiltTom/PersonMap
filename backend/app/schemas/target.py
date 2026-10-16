from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, model_validator, field_validator, Field
from app.schemas.identifiers import TypedIdentifier
from app.schemas.footprint import FootprintInput, UsernameSeed


class TargetCreate(BaseModel):
    input_version: int = Field(default=1, ge=1, le=2)
    given_names: Optional[str] = None
    family_names: Optional[str] = None
    emails: list[str] = Field(default_factory=list, max_length=30)
    usernames: list[UsernameSeed] = Field(default_factory=list, max_length=30)
    phones: list[str] = Field(default_factory=list, max_length=30)
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    dni: Optional[str] = None
    university: Optional[str] = None
    description: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    identifiers: list[TypedIdentifier] = Field(default_factory=list, max_length=30)

    @model_validator(mode="before")
    @classmethod
    def detect_v2(cls, values):
        if isinstance(values, dict):
            fields = ("given_names", "family_names", "emails", "usernames", "phones")
            # Full V1 model dumps contain new fields with empty defaults. They
            # must still round-trip, but populated V2 fields cannot opt out.
            populated = any(values.get(key) for key in fields)
            implicit = "input_version" not in values and any(key in values for key in fields)
            if populated or implicit:
                values = {**values, "input_version": 2}
        return values

    @model_validator(mode="after")
    def normalize_v2(self):
        if self.input_version == 2:
            if any((self.dni, self.university, self.description, self.identifiers)):
                raise ValueError("La entrada V2 solo admite nombres, correos, alias y teléfonos.")
            canonical = FootprintInput(given_names=self.given_names, family_names=self.family_names,
                emails=self.emails, usernames=self.usernames, phones=self.phones)
            for field in ("given_names", "family_names", "emails", "usernames", "phones"):
                setattr(self, field, getattr(canonical, field))
            # Scalars are mirrors, never a second independent set of seeds.
            name = " ".join(part for part in (self.given_names, self.family_names) if part) or None
            mirrors = {"full_name": name, "email": next(iter(self.emails), None),
                       "username": self.usernames[0].username if self.usernames else None,
                       "phone": next(iter(self.phones), None)}
            for field, value in mirrors.items():
                if getattr(self, field) is not None and getattr(self, field) != value:
                    raise ValueError("No mezcles campos únicos antiguos con entradas V2 diferentes.")
                setattr(self, field, value)
        return self

    def persistence_values(self) -> dict:
        values = self.model_dump(exclude={"input_version", "given_names", "family_names", "emails", "usernames", "phones", "identifiers"})
        extra = dict(values.get("extra_data") or {})
        # Never accept caller-supplied provenance/consent through the JSON escape hatch.
        for key in ("footprint_input", "subject_consent"):
            extra.pop(key, None)
        if self.input_version == 2:
            extra["footprint_input"] = FootprintInput(given_names=self.given_names, family_names=self.family_names,
                emails=self.emails, usernames=self.usernames, phones=self.phones).model_dump(mode="json")
        if self.identifiers:
            extra["identifiers"] = [item.model_dump() for item in self.identifiers]
        values["extra_data"] = extra
        return values

    @field_validator("dni", mode="before")
    @classmethod
    def validate_dni(cls, value):
        from app.tools.dni_public import normalize_dni
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        normalized = normalize_dni(value)
        if normalized is None:
            raise ValueError("El DNI debe contener exactamente ocho dígitos ASCII.")
        return normalized

    @model_validator(mode="after")
    def check_at_least_one_identifier(self) -> "TargetCreate":
        has_identifier = any([
            bool(self.full_name and self.full_name.strip()),
            bool(self.email and self.email.strip()),
            bool(self.username and self.username.strip()),
            bool(self.phone and self.phone.strip()),
            bool(self.dni and self.dni.strip()),
            bool(self.identifiers),
        ])
        if not has_identifier:
            raise ValueError(
                "Debe ingresar al menos un dato identificador del objetivo: "
                "nombre completo, correo, nombre de usuario, teléfono, DNI o identificador tipado."
            )
        return self


class TargetRead(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    dni: Optional[str] = None
    university: Optional[str] = None
    description: Optional[str] = None
    extra_data: Dict[str, Any] = Field(default_factory=dict)
    footprint_input: FootprintInput | None = None
    created_at: datetime

    @field_validator("extra_data", mode="before")
    @classmethod
    def historical_empty_extra(cls, value):
        return {} if value is None else value

    model_config = ConfigDict(from_attributes=True)
