"""Typed public identifiers; numeric IDs are never guessed to be usernames."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


IdentifierType = Literal["username", "gaia_id", "steam_id", "vk_id", "qq_id", "bilibili_id",
                         "yandex_public_id", "yelp_userid", "ok_id", "wikimapia_uid", "uidme_uguid", "orcid"]
NUMERIC_TYPES = {"gaia_id", "steam_id", "vk_id", "qq_id", "bilibili_id", "ok_id", "wikimapia_uid"}
CASE_SENSITIVE_TYPES = {"yelp_userid", "yandex_public_id", "uidme_uguid"}
TypedIdentifierType = Literal["gaia_id", "steam_id", "vk_id", "qq_id", "bilibili_id",
                              "yandex_public_id", "yelp_userid", "ok_id", "wikimapia_uid", "uidme_uguid", "orcid"]


class PublicIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    value: str = Field(min_length=1, max_length=100)
    id_type: IdentifierType

    @model_validator(mode="after")
    def valid_value(self):
        pattern = r"[\w.-]+" if self.id_type == "username" else r"[A-Za-z0-9_.-]+"
        if not re.fullmatch(pattern, self.value):
            raise ValueError("Usa un identificador, sin URLs, correo, espacios ni operadores.")
        if self.id_type in NUMERIC_TYPES and not self.value.isdecimal():
            raise ValueError("Este tipo requiere un identificador numérico.")
        if self.id_type == "orcid":
            if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", self.value):
                raise ValueError("Formato ORCID inválido.")
            total = 0
            for digit in self.value.replace("-", "")[:-1]:
                total = (total + int(digit)) * 2
            check = (12 - total % 11) % 11
            if self.value[-1] != ("X" if check == 10 else str(check)):
                raise ValueError("Dígito de control ORCID inválido.")
        return self


class TypedIdentifier(PublicIdentifier):
    id_type: TypedIdentifierType
