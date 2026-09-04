from typing import Dict, List, Optional
from app.tools.base import BaseTool, TargetContext, ToolCategory
from app.tools.username_finder import UsernameFinderTool
from app.tools.email_checker import EmailCheckerTool
from app.tools.email_enumerator import EmailEnumeratorTool
from app.tools.gravatar_deep import GravatarDeepTool
from app.tools.google_account_osint import GoogleAccountOSINTTool
from app.tools.keybase_resolver import KeybaseResolverTool
from app.tools.social_url_extractor import SocialUrlExtractorTool
from app.tools.wikipedia_edits import WikipediaEditsTool
from app.tools.social_verifier import SocialVerifierTool
from app.tools.search_dorker import SearchDorkerTool
from app.tools.academic_finder import AcademicFinderTool
from app.tools.dni_lookup import DniLookupTool
from app.tools.breach_checker import BreachCheckerTool
from app.tools.infostealer_checker import InfostealerCheckerTool
from app.tools.phone_lookup import PhoneLookupTool
from app.tools.github_deep_scanner import GitHubDeepScannerTool
from app.tools.reverse_image_search import ReverseImageSearchTool


class ToolRegistry:
    """Central registry of all available OSINT tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        # Username & Profile Hunting (WhatsMyName / Keybase / Wikipedia)
        self.register(UsernameFinderTool())
        self.register(KeybaseResolverTool())
        self.register(WikipediaEditsTool())

        # Email Intelligence & Silent Enumeration (Holehe / Gravatar / Domain / Google)
        self.register(EmailCheckerTool())
        self.register(EmailEnumeratorTool())
        self.register(GravatarDeepTool())
        self.register(GoogleAccountOSINTTool())

        # Code & Developer Forensics
        self.register(GitHubDeepScannerTool())

        # URL Extraction & Deep Social Scraping
        self.register(SocialUrlExtractorTool())
        self.register(SocialVerifierTool())

        # Search Engines & Academic Footprint
        self.register(SearchDorkerTool())
        self.register(AcademicFinderTool())

        # National Identity & Telephony
        self.register(DniLookupTool())
        self.register(PhoneLookupTool())

        # Compromised Credentials & Breaches
        self.register(BreachCheckerTool())
        # Registros de infostealer: complementa al anterior, no lo sustituye.
        # Una brecha es un fallo de un tercero; un infostealer, del equipo de la
        # propia persona. Solo se ejecuta con consentimiento explícito.
        self.register(InfostealerCheckerTool())

        # Reverse Image / Avatar Correlation (optional, requires API key)
        self.register(ReverseImageSearchTool())

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get_runnable_tools(self, context: TargetContext, executed_tool_names: List[str] | None = None) -> List[BaseTool]:
        """Return all tools that CAN execute with the current context and haven't already run."""
        executed = set(executed_tool_names or [])
        return [
            tool for tool in self._tools.values()
            if tool.name not in executed and tool.can_run(context)
        ]

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_by_category(self, category: ToolCategory) -> List[BaseTool]:
        return [tool for tool in self._tools.values() if tool.category == category]


tool_registry = ToolRegistry()
