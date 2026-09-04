from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/person_map"

    # LLM (Optional - model agnostic via LiteLLM)
    # Examples:
    # - "gemini/gemini-2.0-flash"
    # - "groq/llama-3.3-70b-versatile"
    # - "openai/gpt-4o-mini"
    # - "ollama/llama3"
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None

    # Server & Security
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # HTTP resilience layer (shared by every OSINT tool via app.tools.http_client)
    # Global cap on concurrent outbound requests across the whole process, to avoid
    # hammering the network stack / getting the server's own IP flagged by WAFs.
    http_max_concurrency: int = 40

    # Username enumeration: how many sites from the bundled WhatsMyName dataset
    # to actually check per username. The dataset itself has 700+ entries;
    # raise this as high as your infrastructure/rate-limits comfortably allow.
    username_scan_max_sites: int = 500

    # Reverse image / avatar search (optional, both are pluggable backends).
    # Leave unset to keep this feature disabled (graceful no-op), same pattern
    # as the optional LLM integration below.
    bing_visual_search_key: Optional[str] = None
    serpapi_key: Optional[str] = None

    @property
    def ai_enabled(self) -> bool:
        """Returns True only if both model and API key are configured."""
        return bool(self.llm_model and self.llm_api_key)

    @property
    def reverse_image_enabled(self) -> bool:
        """Returns True if at least one reverse-image-search backend is configured."""
        return bool(self.bing_visual_search_key or self.serpapi_key)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
