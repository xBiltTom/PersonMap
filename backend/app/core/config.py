from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/person_map"

    # LLM (Optional - model agnostic via LiteLLM)
    # Examples:
    # - "gemini/gemini-3.6-flash"   <- verificado con function calling (2026-09-04)
    # - "groq/llama-3.3-70b-versatile"
    # - "openai/gpt-4o-mini"
    # - "ollama/llama3"
    #
    # OJO con las versiones de Gemini: el listado de `v1beta/models` incluye
    # modelos que una clave nueva NO puede usar. `gemini-2.5-flash` aparece en la
    # lista y devuelve 404 "no longer available to new users", y `gemini-2.0-flash`
    # ya no aparece. Comprobar el modelo concreto con curl antes de fijarlo, y
    # fijar una versión explícita en vez de un alias móvil como
    # `gemini-flash-latest`: el artículo necesita saber qué modelo produjo cada
    # medición.
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None

    # Modelo de embeddings para la señal semántica del resolutor de identidad
    # (compara biografías que dicen lo mismo con palabras distintas: "UNMSM"
    # frente a "Universidad Nacional Mayor de San Marcos"). Se resuelve por
    # LiteLLM igual que el modelo de chat, así que admite cualquier proveedor:
    #   openai/text-embedding-3-small · gemini/text-embedding-004 · ollama/nomic-embed-text
    # Vacío = señal desactivada; el sistema sigue funcionando con cotejo léxico.
    llm_embedding_model: Optional[str] = None

    # --- Motor híbrido (tercera estrategia del orquestador) -----------------
    # `hybrid` ejecuta el barrido heurístico completo y después deja que el LLM
    # pida solo las llamadas que cubran huecos. No sustituye a `rules` ni a
    # `agentic`: los tres siguen siendo condiciones experimentales independientes.
    #
    # Turnos máximos de la capa de refinamiento. Dos bastan (uno para proponer,
    # otro para reaccionar a lo que devolvieron las herramientas) y acotan el
    # gasto de tokens y la latencia, que en una sustentación en vivo importa.
    hybrid_max_refinement_turns: int = 2

    # Arbitraje por LLM de los hallazgos en la zona ambigua (0.40-0.70 de
    # probabilidad de atribución). Apagado a propósito: es no determinista, y en
    # una demo en vivo significa que la misma entrada puede producir clusters
    # distintos delante del jurado. Cuando se activa, el veredicto queda
    # registrado en los metadatos del hallazgo y NUNCA sobrescribe el
    # `identity_score` del modelo, de modo que el histograma y la calibración del
    # artículo siguen midiendo Fellegi-Sunter puro.
    hybrid_llm_arbitration: bool = False
    # Tope de hallazgos que se envían a arbitrar por investigación.
    hybrid_arbitration_max_entities: int = 12

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
    # Descarta los resultados que no contienen literalmente el término
    # entrecomillado del dork. Tavily busca por relevancia semántica, así que un
    # dork de un correo inexistente devuelve la web del dominio: un falso
    # positivo que en OSINT es peor que no obtener nada. Su parámetro nativo
    # `exact_match` no sirve (devuelve cero resultados siempre), de ahí que la
    # comprobación se haga del lado del cliente.
    tavily_require_literal_match: bool = True

    @property
    def ai_enabled(self) -> bool:
        """Returns True only if both model and API key are configured."""
        return bool(self.llm_model and self.llm_api_key)

    @property
    def reverse_image_enabled(self) -> bool:
        """Returns True if at least one reverse-image-search backend is configured."""
        return bool(self.bing_visual_search_key or self.serpapi_key)

    @property
    def semantic_matching_enabled(self) -> bool:
        """True si hay modelo de embeddings y clave para invocarlo."""
        return bool(self.llm_embedding_model and self.llm_api_key)

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
