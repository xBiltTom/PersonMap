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

    # --- Motor híbrido (tercera estrategia del orquestador) -----------------
    # `hybrid` ejecuta el barrido heurístico completo y después deja que el LLM
    # pida solo las llamadas que cubran huecos. No sustituye a `rules` ni a
    # `agentic`: los tres siguen siendo condiciones experimentales independientes.
    #
    # Turnos máximos de la capa de refinamiento. Dos bastan (uno para proponer,
    # otro para reaccionar a lo que devolvieron las herramientas) y acotan el
    # gasto de tokens y la latencia, que en una sustentación en vivo importa.
    hybrid_max_refinement_turns: int = 2

    # Server & Security
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

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
    # El catálogo va ordenado en dos niveles —primero los 667 sitios curados de
    # WhatsMyName, después la cola larga de Maigret—, así que recortar por aquí
    # nunca quita cobertura de las plataformas importantes: solo acorta la cola.
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
    # Fracción máxima del presupuesto global que puede tomar una sola tool.
    tool_concurrency_share: float = 0.6

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
