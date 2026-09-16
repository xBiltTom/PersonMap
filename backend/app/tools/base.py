from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCategory(str, Enum):
    EMAIL = "email"
    USERNAME = "username"
    PHONE = "phone"
    SOCIAL = "social"
    ACADEMIC = "academic"
    BREACH = "breach"
    SEARCH = "search"
    DOCUMENT = "document"
    IMAGE = "image"


class TargetContext(BaseModel):
    """Accumulated context of all known and discovered information about the target."""
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    dni: Optional[str] = None
    university: Optional[str] = None
    description: Optional[str] = None

    discovered_emails: List[str] = Field(default_factory=list)
    discovered_usernames: List[str] = Field(default_factory=list)
    discovered_names: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

    def all_emails(self) -> List[str]:
        emails = []
        if self.email and self.email.strip():
            emails.append(self.email.strip().lower())
        for e in self.discovered_emails:
            e_clean = e.strip().lower()
            if e_clean not in emails:
                emails.append(e_clean)
        return emails

    def all_usernames(self) -> List[str]:
        usernames = []
        if self.username and self.username.strip():
            usernames.append(self.username.strip())
        for u in self.discovered_usernames:
            u_clean = u.strip()
            if u_clean not in usernames:
                usernames.append(u_clean)
        return usernames


class ToolFinding(BaseModel):
    """Standardized finding returned by any OSINT tool."""
    entity_type: str                  # 'social_account', 'email', 'paper', 'breach', 'search_mention'
    platform: Optional[str] = None    # 'github', 'instagram', 'google_scholar', etc.
    value: str                        # URL, email, handle, title
    display_name: Optional[str] = None
    metadata_info: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5           # Priorización interna de detecciones al deduplicar fuentes.
    evidence_urls: List[str] = Field(default_factory=list)


class BaseTool(ABC):
    """Abstract base class for all OSINT tools in person-map."""
    name: str
    description: str
    category: ToolCategory
    # List of field names in TargetContext of which at least one must be non-empty
    required_inputs: List[str]

    @abstractmethod
    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        """Execute OSINT tool asynchronously and return findings."""
        pass

    def can_run(self, context: TargetContext) -> bool:
        """Verify if context has at least one required input to run this tool."""
        for field in self.required_inputs:
            val = getattr(context, field, None)
            if val and (isinstance(val, list) and len(val) > 0 or isinstance(val, str) and val.strip()):
                return True
        return False
