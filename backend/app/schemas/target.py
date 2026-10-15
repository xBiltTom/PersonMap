from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, model_validator, field_validator, Field
from app.schemas.identifiers import TypedIdentifier


class TargetCreate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    dni: Optional[str] = None
    university: Optional[str] = None
    description: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    identifiers: list[TypedIdentifier] = Field(default_factory=list, max_length=30)

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
    extra_data: Dict[str, Any] = {}
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
