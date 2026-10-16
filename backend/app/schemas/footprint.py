"""V2 input/provenance contracts. Detection is never subject confirmation."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

ProvenanceStatus = Literal["declared", "discovered", "confirmed", "rejected", "uncertain"]


class UsernameSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    platform: str | None = Field(default=None, max_length=100)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        if not isinstance(value, str):
            raise ValueError("El alias debe ser texto.")
        value = value.strip().lstrip("@")
        if not re.fullmatch(r"[\w.-]{1,100}", value):
            raise ValueError("El alias no debe contener espacios ni URLs.")
        return value

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value):
        return value.strip().casefold() or None if isinstance(value, str) else value


class DataProvenance(BaseModel):
    """Origin and human decision are independent of source/existence verification.

    Future review writes must be authenticated server operations, never tool output.
    No review mutation endpoint is implemented in Foundation V2.
    """
    origin: Literal["subject", "automatic", "legacy"]
    status: ProvenanceStatus
    subject_asserted: bool = False
    evidence_urls: list[str] = Field(default_factory=list)
    # Re-analyzing an input email/phone is not discovering a new identifier.
    # This exemption never applies to accounts, documents or breach records.
    matches_declared_identifier: bool = False

    @computed_field
    @property
    def needs_review(self) -> bool:
        return (self.origin == "automatic" and self.status in {"discovered", "uncertain"}
                and not self.matches_declared_identifier)


class DeclaredSeed(BaseModel):
    kind: Literal["name", "email", "username", "phone"]
    value: str
    platform: str | None = None
    provenance: DataProvenance = Field(default_factory=lambda: DataProvenance(
        origin="subject", status="declared", subject_asserted=True))


class FootprintInput(BaseModel):
    """Canonical declared input, persisted in Target.extra_data.footprint_input."""
    version: Literal[2] = 2
    given_names: str | None = Field(default=None, max_length=120)
    family_names: str | None = Field(default=None, max_length=120)
    emails: list[str] = Field(default_factory=list, max_length=30)
    usernames: list[UsernameSeed] = Field(default_factory=list, max_length=30)
    phones: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("given_names", "family_names", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return " ".join(value.split()) or None if isinstance(value, str) else value

    @field_validator("emails")
    @classmethod
    def normalize_emails(cls, values):
        result = []
        for value in values:
            value = value.strip().lower()
            if len(value) > 254 or not re.fullmatch(r'[^\s@<>"\\\x00-\x1f\x7f]{1,64}@[^\s@<>"\\\x00-\x1f\x7f]+\.[^\s@<>"\\\x00-\x1f\x7f]+', value):
                raise ValueError("Correo no válido.")
            if value not in result:
                result.append(value)
        return result

    @field_validator("usernames")
    @classmethod
    def dedupe_usernames(cls, values):
        # Preserve case-sensitive handles; namespaces must never be collapsed.
        return list({(item.username, item.platform): item for item in values}.values())

    @field_validator("phones")
    @classmethod
    def normalize_phones(cls, values):
        from app.tools.phone_numbers import phone_identity
        result = []
        for value in values:
            normalized = phone_identity(value)
            if normalized is None:
                raise ValueError("Teléfono no válido; incluye el prefijo internacional (por defecto PE).")
            if normalized not in result:
                result.append(normalized)
        return result

    @computed_field
    @property
    def declared_seeds(self) -> list[DeclaredSeed]:
        name = " ".join(part for part in (self.given_names, self.family_names) if part)
        return ([DeclaredSeed(kind="name", value=name)] if name else []) + [
            *[DeclaredSeed(kind="email", value=value) for value in self.emails],
            *[DeclaredSeed(kind="username", value=item.username, platform=item.platform) for item in self.usernames],
            *[DeclaredSeed(kind="phone", value=value) for value in self.phones],
        ]


def footprint_input(target) -> FootprintInput | None:
    raw = (getattr(target, "extra_data", None) or {}).get("footprint_input")
    return FootprintInput.model_validate(raw) if raw else None


def discovered_provenance(evidence_urls=(), *, matches_declared_identifier=False) -> dict:
    return DataProvenance(origin="automatic", status="discovered",
        evidence_urls=list(evidence_urls), matches_declared_identifier=matches_declared_identifier).model_dump(mode="json")


def is_declared_identifier(target, kind: str, value: str, platform: str | None = None) -> bool:
    """Exact atomic inputs only. A matching account handle is NOT an input account."""
    if kind not in {"email", "username", "phone"}:
        return False
    declared = footprint_input(target)
    if not declared:
        return False
    if kind == "email":
        return value.strip().lower() in declared.emails
    if kind == "phone":
        from app.tools.phone_numbers import phone_identity
        return phone_identity(value) in declared.phones
    namespace = platform.strip().casefold() or None if platform else None
    return any(item.username == value.strip().lstrip("@") and item.platform == namespace
               for item in declared.usernames)


def account_ownership(seeds, platform, username) -> dict:
    """Only an exact declared namespace associates an account with the subject.

    Stable seed IDs survive JSON reloads and do not identify unrelated aliases.
    """
    import hashlib
    import json
    from app.social.capabilities import canonical_platform
    for seed in seeds:
        if (seed.kind == "username" and seed.platform
                and canonical_platform(seed.platform) == canonical_platform(platform)
                and seed.value.casefold() == username.lstrip("@").casefold()):
            ref = {"kind": seed.kind, "value": seed.value, "platform": seed.platform}
            return {"status": "subject_declared", "needs_review": False,
                    "seed_id": hashlib.sha256(json.dumps(ref, sort_keys=True).encode()).hexdigest(), "seed": ref}
    return {"status": "unverified", "needs_review": True}
