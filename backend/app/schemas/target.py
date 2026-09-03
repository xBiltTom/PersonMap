from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, model_validator


class TargetCreate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    dni: Optional[str] = None
    university: Optional[str] = None
    description: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def check_at_least_one_identifier(self) -> "TargetCreate":
        has_identifier = any([
            bool(self.full_name and self.full_name.strip()),
            bool(self.email and self.email.strip()),
            bool(self.username and self.username.strip()),
            bool(self.phone and self.phone.strip()),
            bool(self.dni and self.dni.strip()),
        ])
        if not has_identifier:
            raise ValueError(
                "Debe ingresar al menos un dato identificador del objetivo: "
                "nombre completo, correo, nombre de usuario, teléfono o DNI."
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
