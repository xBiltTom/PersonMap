from typing import Optional
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Fair is selected per investigation, never inferred from normal strategies.
    fair_total_deadline_seconds: float = Field(default=225, ge=1, le=600, allow_inf_nan=False)
    fair_finalization_seconds: float = Field(default=20, gt=0, le=120, allow_inf_nan=False)
    fair_cancellation_seconds: float = Field(default=6, gt=0, le=30, allow_inf_nan=False)
    fair_checkpoint_seconds: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    fair_max_waves: int = Field(default=3, ge=1, le=3)
    fair_parallelism: int = Field(default=16, ge=1, le=32)
    fair_username_sites: int = Field(default=100, ge=1, le=200)
    fair_search_queries: int = Field(default=8, ge=1, le=30)
    fair_apify_platforms: list[str] = Field(default_factory=lambda: ["instagram", "tiktok", "youtube"])
    fair_disabled_sources: list[str] = Field(default_factory=list)

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

    # --- Motor híbrido (tercera estrategia del orquestador) -----------------
    # `hybrid` ejecuta el barrido heurístico completo y después deja que el LLM
    # pida solo las llamadas que cubran huecos. No sustituye a `rules` ni a
    # `agentic`: los tres siguen siendo condiciones experimentales independientes.
    #
    # Turnos máximos de la capa de refinamiento. Dos bastan (uno para proponer,
    # otro para reaccionar a lo que devolvieron las herramientas) y acotan el
    # gasto de tokens y la latencia, que en una sustentación en vivo importa.
    hybrid_max_refinement_turns: int = 2

    # Admission budgets, separate from per-tool request/rate/concurrency limits.
    pivot_frontier_enabled: bool = True
    pivot_max_per_round: int = Field(default=12, ge=1, le=1000)
    pivot_max_total: int = Field(default=128, ge=1, le=10000)
    pivot_max_weak_per_round: int = Field(default=2, ge=0, le=1000)
    pivot_min_priority: int = Field(default=0, ge=0, le=1000)
    pivot_round_cost_budget: int = Field(default=100, ge=1, le=10000)
    pivot_deep_max_rounds: int = Field(default=8, ge=4, le=100)
    pivot_corroboration_bonus: int = Field(default=30, ge=0, le=40)

    # Server & Security
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # The MCP bridge shares this backend's process and database. No LLM key needed.
    mcp_enabled: bool = True
    mcp_api_key: Optional[SecretStr] = None
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    frontend_url: str = "http://localhost:3000"
    mcp_max_parallel_tools: int = 3
    mcp_username_fast_sites: int = 200
    mcp_review_max_queries: int = 3

    # --- Presupuesto de concurrencia HTTP ------------------------------------
    # Compartido por todas las tools a través de app.tools.http_client.
    #
    # El diseño anterior tenía un único semáforo global de 40 peticiones y nada
    # más. Eso confundía dos cosas que no son la misma: **cortesía** con cada
    # host y **consumo de recursos** del proceso. Enviar 500 peticiones a 500
    # hosts distintos no es descortés con nadie, pero el tope global lo trataba
    # igual que 500 peticiones al mismo host. El resultado medido: una
    # investigación tardaba 530 s, y `username_finder` acaparaba 30 de las 40
    # ranuras, dejando 10 para las otras diecisiete herramientas de la ronda.
    #
    # Ahora son dos límites con propósitos distintos:
    #   - `http_max_per_host` es la cortesía real. Es el que evita que un sitio
    #     nos bloquee, y el que la Fase 4.2 necesitará para respetar el límite de
    #     Hudson Rock (50 req/10 s por host).
    #   - `http_max_concurrency` es el guardarraíl del proceso (sockets, CPU).
    #     Con la cortesía garantizada por host, puede ser mucho más alto.
    http_max_concurrency: int = 120
    http_max_per_host: int = 4

    # Enumeración de alias: cuántos sitios del catálogo unificado
    # (WhatsMyName + Maigret, normalizados en memoria) se comprueban por alias.
    #
    # Primero las plataformas curadas con su motor nativo y todas las recetas
    # de WhatsMyName (incluidos POST y variantes); después la cola de Maigret.
    # Un tope muy bajo o el modo fast pueden recortar también WhatsMyName.
    #
    # Medido sobre `@torvalds`: 500 sitios → 89 hallazgos en 29 s;
    # 3.396 sitios → 234 hallazgos en 152 s.
    username_scan_max_sites: int = 3400

    # Tope de alias distintos que se barren por investigación.
    #
    # Es el que acota de verdad la duración: cada alias nuevo cuesta un barrido
    # entero del catálogo, y el pivoteo puede descubrir muchos. Con el catálogo
    # completo, tres alias son ~7,5 min de barrido, que deja margen dentro de un
    # presupuesto de 15 minutos para el resto de herramientas y la capa de IA.
    username_scan_max_aliases: int = 3
    # Ranuras simultáneas de `username_finder`. Antes era una constante de 30 en
    # la propia tool, invisible desde la configuración y descuadrada con el tope
    # global. Se expone aquí porque es la palanca que decide cuánto dura una
    # demo, y se acota abajo a una fracción del presupuesto global para que
    # ninguna herramienta pueda dejar sin ranuras al resto de la ronda.
    username_scan_concurrency: int = 60
    maigret_request_timeout: float = 10.0
    maigret_worker_timeout: float = 900.0
    maigret_enrich: bool = True
    maigret_tags: list[str] = []
    maigret_site_names: list[str] = []
    maigret_excluded_tags: list[str] = []
    maigret_keywords: list[str] = []
    maigret_parse: bool = True
    maigret_retries: int = Field(default=1, ge=0, le=5)
    maigret_max_identifiers: int = Field(default=10, ge=0, le=100)
    maigret_max_parse_urls: int = Field(default=10, ge=0, le=100)
    maigret_max_permutations: int = Field(default=10, ge=0, le=100)
    maigret_cookie_file: Optional[str] = None
    maigret_tor_proxy: Optional[SecretStr] = None
    maigret_i2p_proxy: Optional[SecretStr] = None
    maigret_proxy: Optional[SecretStr] = None
    maigret_solver_url: Optional[str] = None
    maigret_check_domains: bool = False
    maigret_tool_timeout: float = Field(default=1800, ge=30, le=7200)
    maigret_database_file: Optional[str] = None
    maigret_queue_grace: float = Field(default=30, ge=0, le=120)
    maigret_solver_timeout: float = Field(default=65, ge=5, le=120)
    maigret_solver_concurrency: int = Field(default=4, ge=1, le=10)
    # GHunt runs in a separate Python environment: its HTTPX/Pillow pins conflict
    # with the API. No credentials are accepted through investigation inputs.
    ghunt_enabled: bool = True
    ghunt_python: Optional[str] = None
    ghunt_credentials_file: Optional[str] = None
    ghunt_services: list[str] = ["maps", "calendar", "play_games"]
    ghunt_max_queries: int = Field(default=3, ge=0, le=20)
    ghunt_max_drive_files: int = Field(default=3, ge=0, le=20)
    ghunt_worker_timeout: float = Field(default=180, ge=10, le=600)
    ghunt_request_timeout: float = Field(default=20, ge=1, le=60)
    ghunt_max_requests: int = Field(default=80, ge=1, le=300)
    ghunt_max_events: int = Field(default=20, ge=0, le=100)
    # Reviewed Holehe techniques share HTTP limits; no CLI dependency changes.
    email_enum_sites: list[str] = []
    email_enum_max_emails: int = Field(default=3, ge=0, le=20)
    email_enum_concurrency: int = Field(default=6, ge=1, le=30)
    email_enum_request_timeout: float = Field(default=7, ge=1, le=30)
    email_enum_probe_timeout: float = Field(default=20, ge=1, le=90)
    email_enum_batch_timeout: float = Field(default=90, ge=1, le=300)
    # Fracción máxima del presupuesto global que puede tomar una sola tool.
    tool_concurrency_share: float = 0.6

    # Enrichment of discovered profile URLs, bounded per investigation.
    phone_max_numbers: int = 3
    # Select paid packages explicitly; an empty list keeps all lookups local.
    phone_twilio_fields: list[str] = []
    phone_twilio_api_key: Optional[str] = None
    phone_twilio_api_secret: Optional[SecretStr] = None

    social_verify_concurrency: int = 8
    social_verify_max_urls: int = 300
    social_verify_url_timeout: float = 20.0

    # Reverse image / avatar search (optional, both are pluggable backends).
    # Leave unset to keep this feature disabled (graceful no-op), same pattern
    # as the optional LLM integration below.
    bing_visual_search_key: Optional[str] = None
    serpapi_key: Optional[str] = None

    # DNI: openly accessible publications; no private lookup mirrors.
    # Kept for compatibility with older deployments; no longer consumed.
    apis_net_pe_token: Optional[str] = None
    dni_public_source_urls: list[str] = []
    dni_max_public_sources: int = 4
    pdf_ocr_enabled: bool = True
    pdf_ocr_max_pages: int = 3
    pdf_ocr_timeout_seconds: float = 20
    pdf_ocr_languages: str = "auto"

    # --- Motor de búsqueda para dorking -------------------------------------
    # Tavily (https://tavily.com) es un buscador diseñado para agentes: devuelve
    # JSON estructurado con puntuación de relevancia, en lugar del HTML que hay
    # que raspar de DuckDuckGo. Su nivel gratuito da 1.000 créditos al mes y una
    # búsqueda `basic` cuesta 1 crédito.
    #
    # Sin clave, `search_dorker` cae automáticamente al scraping de DuckDuckGo,
    # sin exigir claves; la disponibilidad externa se registra en diagnósticos.
    tavily_api_key: Optional[str] = None
    # "basic" (1 crédito) o "advanced" (2 créditos, más contexto por resultado).
    tavily_search_depth: str = "basic"
    # Tope de dorks por investigación: acota el gasto de créditos, ya que el
    # motor puede re-ejecutar la herramienta en rondas posteriores tras pivotar.
    tavily_max_queries: int = 5
    # Provider-independent budget. None keeps older TAVILY_MAX_QUERIES deployments compatible.
    search_max_queries: Optional[int] = None
    tavily_max_results: int = 8
    # Sesga los resultados hacia el país del público objetivo. ISO en inglés.
    tavily_country: Optional[str] = "peru"
    # Native exact matching complements local validation; phone format alternatives use OR.
    tavily_require_literal_match: bool = True
    tavily_exact_match: bool = True
    search_max_queries_per_round: int = 5
    search_query_concurrency: int = 3
    search_timeout_seconds: float = 90
    search_read_pages: bool = False
    search_max_pages: int = 2
    tinyfish_api_key: Optional[SecretStr] = None
    tinyfish_location: str = "PE"
    tinyfish_language: str = "es"
    tinyfish_fetch_enabled: bool = False
    # Independent web index, optional; does not enable paid requests without a key.
    brave_api_key: Optional[SecretStr] = None
    brave_country: str = "PE"
    brave_search_language: str = "es"
    openalex_api_key: Optional[SecretStr] = None
    crossref_enabled: bool = True
    # Operator contact only, never populated from an investigated address.
    crossref_mailto: Optional[str] = None
    academic_max_names: int = 3
    academic_max_orcids: int = 3
    academic_max_dois: int = 3
    academic_max_requests: int = 24
    academic_results_per_query: int = 10
    academic_request_timeout: float = 8
    academic_batch_timeout: float = 60
    github_api_token: Optional[SecretStr] = None

    # Optional public social enrichment. No Actor runs without operator opt-in,
    # an allowlisted platform AND the subject consent recorded on the target.
    apify_enabled: bool = False
    apify_token: Optional[SecretStr] = None
    apify_platforms: list[str] = Field(default_factory=lambda: ["instagram", "tiktok"])
    apify_actor_builds: dict[str, str] = Field(default_factory=dict)
    apify_max_actors: int = Field(default=2, ge=0, le=10)
    apify_max_runs: int = Field(default=2, ge=0, le=20)
    apify_max_profiles_per_actor: int = Field(default=3, ge=1, le=30)
    apify_max_content_items_per_profile: int = Field(default=10, ge=1, le=100)
    # Deprecated compatibility field; limits are now profiles and content separately.
    apify_max_items_per_actor: int = Field(default=5, ge=1, le=100)
    apify_dataset_page_size: int = Field(default=5, ge=1, le=100)
    apify_run_timeout: int = Field(default=60, ge=5, le=300)
    apify_batch_timeout: float = Field(default=150, ge=1, le=600)
    apify_request_timeout: float = Field(default=15, ge=1, le=60)
    apify_max_retries: int = Field(default=1, ge=0, le=3)  # GET only, never run starts
    apify_parallelism: int = Field(default=1, ge=1, le=4)
    apify_max_charge_per_run_usd: float = Field(default=0.05, gt=0, le=5, allow_inf_nan=False)
    apify_max_charge_per_investigation_usd: float = Field(default=0.10, ge=0, le=10, allow_inf_nan=False)
    apify_max_response_bytes: int = Field(default=2_000_000, ge=1024, le=8_000_000)

    @property
    def brave_enabled(self) -> bool:
        return bool(self.brave_api_key and self.brave_api_key.get_secret_value().strip())

    @property
    def search_query_budget(self) -> int:
        return max(0, self.search_max_queries if self.search_max_queries is not None else self.tavily_max_queries)

    @property
    def tinyfish_enabled(self) -> bool:
        return bool(self.tinyfish_api_key and self.tinyfish_api_key.get_secret_value().strip())

    def tool_concurrency_budget(self, requested: int) -> int:
        """
        Ranuras que puede tomar una sola herramienta, acotadas a su cuota.

        Sin este tope, una tool de enumeración pide 500 comprobaciones a la vez
        y mata de inanición a las otras diecisiete de la misma ronda. La cuota
        se aplica sobre el presupuesto global, así que subir o bajar
        `http_max_concurrency` reparte automáticamente.
        """
        ceiling = max(1, int(self.http_max_concurrency * self.tool_concurrency_share))
        return max(1, min(requested, ceiling))

    @property
    def ai_enabled(self) -> bool:
        """Returns True only if both model and API key are configured."""
        return bool(self.llm_model and self.llm_api_key)

    @property
    def reverse_image_enabled(self) -> bool:
        """Bing Search APIs retired in 2025; only the supported optional provider can run."""
        return bool(self.serpapi_key)

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
