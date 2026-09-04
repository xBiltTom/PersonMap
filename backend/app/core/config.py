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

    # --- Motor de búsqueda para dorking -------------------------------------
    # Tavily (https://tavily.com) es un buscador diseñado para agentes: devuelve
    # JSON estructurado con puntuación de relevancia, en lugar del HTML que hay
    # que raspar de DuckDuckGo. Su nivel gratuito da 1.000 créditos al mes y una
    # búsqueda `basic` cuesta 1 crédito.
    #
    # Sin clave, `search_dorker` cae automáticamente al scraping de DuckDuckGo,
    # de modo que el sistema sigue funcionando al 100% sin configurar nada.
    tavily_api_key: Optional[str] = None
    # "basic" (1 crédito) o "advanced" (2 créditos, más contexto por resultado).
    tavily_search_depth: str = "basic"
    # Tope de dorks por investigación: acota el gasto de créditos, ya que el
    # motor puede re-ejecutar la herramienta en rondas posteriores tras pivotar.
    tavily_max_queries: int = 5
    tavily_max_results: int = 8
    # Sesga los resultados hacia el país del público objetivo. ISO en inglés.
    tavily_country: Optional[str] = "peru"

    @property
    def ai_enabled(self) -> bool:
        """Returns True only if both model and API key are configured."""
        return bool(self.llm_model and self.llm_api_key)

    @property
    def reverse_image_enabled(self) -> bool:
        """Returns True if at least one reverse-image-search backend is configured."""
        return bool(self.bing_visual_search_key or self.serpapi_key)

    @property
    def tavily_enabled(self) -> bool:
        """True si hay clave de Tavily; si no, el dorker usa DuckDuckGo."""
        return bool(self.tavily_api_key and self.tavily_api_key.strip())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
