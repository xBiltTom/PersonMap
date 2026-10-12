# Auditoría de cobertura y arquitectura OSINT — 12 de octubre de 2026

## Resultado y alcance

PersonMap tiene una base útil: 18 herramientas en `ToolRegistry`, un lector público adicional en MCP, tres motores, evidencias externas importables y trazabilidad persistida. El cuello de botella principal era la selección de consultas y la continuidad entre rondas. Incorporar otro catálogo de usernames sin corregir ese flujo habría aumentado solicitudes mucho más que evidencia útil.

Esta revisión implementa mejoras de búsqueda, lectura y reutilización. Las verificaciones de los adaptadores son deterministas, con respuestas HTTP simuladas; el lector PDF también tiene una prueba con un PDF sintético real y Poppler. Las fuentes oficiales se consultaron en la web. **No se midió todavía una mejora de recall en producción ni se ejecutó una investigación sobre una persona durante esta revisión.**

## Problemas encontrados y cambios implementados

| Antes | Ahora | Evidencia local |
| --- | --- | --- |
| Cinco consultas por expediente; escasa presencia de fuentes especializadas en la cola | Presupuesto independiente del proveedor, configurable con `SEARCH_MAX_QUERIES`; perfil de ejemplo con 20 consultas | [Configuración](../backend/app/core/config.py), [.env.example](../.env.example) |
| Consultas centradas en menciones generales y perfiles | Siete ámbitos: general, perfiles, documentos, foros/comentarios indexados, publicaciones, academia y PDFs abiertos | [Buscador](../backend/app/tools/search_dorker.py) |
| Sin nuevos identificadores, el motor podía omitir búsquedas pendientes en rondas siguientes | La clave de ejecución incluye el progreso del buscador; el motor continúa consultas pendientes hasta presupuesto, plan o cuatro rondas | [Motor de reglas](../backend/app/engine/rule_engine.py) |
| El MCP externo podía escribir consultas; el agente interno solo recibía identificadores | `queries` con justificación y dominios en el esquema interno; misma validación Pydantic; argumentos temporales y presupuestos compartidos | [Despacho](../backend/app/agent/tool_dispatch.py) |
| Las consultas con dominios en diferente orden podían repetirse | Deduplicación por consulta y conjunto de dominios | [Pruebas de cobertura](../backend/tests/test_search_coverage.py) |
| Presupuesto y diagnósticos sin resumen de fuentes pendientes | `search_coverage` con planificación, intentos, coincidencias, consultas sin coincidencias verificadas, indisponibilidad y pendientes; visible para MCP y agentes | [Workspace](../backend/app/services/workspace.py) |
| Tavily → TinyFish → DuckDuckGo | Brave opcional entre TinyFish y DuckDuckGo, con extractos adicionales y filtros locales | [Buscador](../backend/app/tools/search_dorker.py) |
| PDFs fuera del lector general | PDF público con capa de texto: hasta 5 MB, primeras 30 páginas, extracción local con timeout, texto acotado y límites explícitos | [Lector](../backend/app/tools/search_reader.py), [pruebas PDF](../backend/tests/test_public_pdf_reader.py) |
| Lecturas complementarias sin snapshot de texto completo acotado | Texto, fecha, hash del texto seleccionado y selección/truncamiento registrados cuando la página verifica la mención | [Lector](../backend/app/tools/search_reader.py) |
| Presupuestos de lectura perdidos al reanudar | URLs leídas y estado del respaldo de lectura incluidos en runtime durable | [Runtime](../backend/app/core/runtime.py) |
| OpenAlex buscaba obras mediante un filtro textual de autor y no contrastaba las autorías devueltas | Candidatos por nombre completo; publicaciones por `author.id`; contraste del ID en `authorships`, ORCID, ubicaciones y PDFs declarados abiertos | [AcademicFinder](../backend/app/tools/academic_finder.py) |
| OpenAlex declaraba aceptar correo, pero devolvía vacío sin nombre | Readiness alineada con nombres iniciales o descubiertos; intentos y errores persistibles | [Pruebas académicas](../backend/tests/test_academic_evidence.py) |
| GitHub volvía a consultar aliases anteriores al recibir un nuevo pivote | Cobertura de aliases intentados por expediente, límite global de aliases, token opcional para endpoints públicos | [GitHub](../backend/app/tools/github_deep_scanner.py) |
| Caída del LLM reiniciaba el contexto y permitía gastar otra vez el presupuesto de búsqueda | El respaldo heurístico recibe el contexto acumulado del agente | [Agente](../backend/app/agent/autonomous_agent.py) |
| Bing Visual Search se presentaba como fuente disponible | Ya no se programa: la API fue retirada; el parser histórico permanece para compatibilidad del código | [Búsqueda de imagen](../backend/app/tools/reverse_image_search.py) |
| Compose enviaba CORS como cadena separada por comas; FastAPI usaba `*` | JSON válido para Settings y middleware que utiliza los orígenes configurados | [Compose](../docker-compose.yml), [FastAPI](../backend/app/main.py) |

El hash identifica el **texto conservado**, no certifica toda la página original ni todo el archivo PDF. La coincidencia literal verifica una mención; no acredita que una cuenta o un autor sea el objetivo.

## Inventario de herramientas existentes

Estado basado en inspección de código y pruebas locales, no en una certificación de disponibilidad en vivo de todos sus endpoints.

| Herramienta | Utilidad | Evaluación / siguiente mejora |
| --- | --- | --- |
| `username_finder` | Catálogos WhatsMyName/Maigret, controles negativos, cobertura fast/deep | Reutilización adecuada; mantener snapshots, controles y salud por sitio. El ejemplo anterior limitaba deep a 500 sitios; ahora permite hasta 3400, limitado al catálogo real |
| `social_verifier` | Datos públicos por plataforma y URLs candidatas | Buena segunda etapa; una respuesta bloqueada no es una cuenta inexistente. Evitar ampliar scraping genérico a fuentes con acceso restringido |
| `social_url_extractor` | Extracción de enlaces públicos | Complementa verificación; falta distinguir sistemáticamente enlace editorial, autor, mención y navegación en documentos complejos |
| `github_deep_scanner` | Perfiles y registros públicos de autoría Git | Mejorada reutilización; todavía falta un diagnóstico durable por endpoint y respetar explícitamente los headers de cuota |
| `keybase_resolver` | Perfiles y pruebas públicas declaradas | Útil para conexiones explícitas; conservar enlaces de pruebas, sin convertirlos en atribución al objetivo |
| `wikipedia_edits` | Actividad pública de una cuenta | Fuente específica; no interpretar automáticamente contenido editado como creencia o identidad |
| `email_checker` | Validación técnica de dirección/dominio | Contexto técnico, no comprobación del dueño de un buzón |
| `email_enumerator` | Señales de registro en servicios | Alta fragilidad. Los controles negativos existentes son necesarios; no ampliar a flujos que envíen recuperación de contraseña |
| `gravatar_deep` | Perfil y enlaces publicados | Buen pivote cuando hay declaración explícita; no sustituye investigación web |
| `google_account_osint` | Señales y recursos públicos de Google | No equivale a un GHunt autenticado. Documentar alcance real; no prometer Maps/Calendar privados |
| `search_dorker` | Descubrimiento web transversal | Principal mejora de esta revisión: ámbitos, continuidad, cobertura y Brave opcional |
| `academic_finder` | Autores, publicaciones y repositorios | Mejorado por IDs, fuentes abiertas y diagnóstico; nombres abreviados continúan siendo un hueco deliberado de precisión |
| `domain_finder` | Dominios y transparencia de certificados | Parte de enlaces observados; los certificados vinculan infraestructura, no propietario humano |
| `dni_lookup` | Menciones en publicaciones abiertas | Mantener separado de espejos privados; el OCR existente se aplica a su caso específico, no todavía al lector general |
| `phone_lookup` | Plan de numeración y enriquecimiento opcional | Un número válido y un enlace WhatsApp no prueban existencia de cuenta ni titularidad |
| `breach_checker` | Exposición indicada por terceros | Auditoría de exposición; no usar datos de filtraciones como combustible para ampliar un expediente público |
| `infostealer_checker` | Exposición adicional con consentimiento explícito | Mantener condición de consentimiento y alcance; no incorporar nuevas fuentes de credenciales |
| `reverse_image_search` | Páginas que reutilizan una imagen, proveedor opcional | Bing retirado; SerpApi requiere clave. No es reconocimiento facial |
| `public_page_reader` (MCP) | Captura de páginas/documentos explícitos | Ahora también PDF con texto. Sigue fuera del registry interno: unificar acceso del agente interno es trabajo pendiente |

## Fuentes nuevas evaluadas y prioridad

| Fuente | Decisión | Motivo y documentación primaria |
| --- | --- | --- |
| Brave Search | **Adaptador implementado, activación opcional** | Índice adicional; extractos adicionales por resultado. No se configura clave ni se contrata un plan en esta revisión. [API oficial](https://api-dashboard.search.brave.com/documentation/services/web-search) |
| Tavily | **Conservar** | El contrato actual documenta búsqueda exacta, restricción de dominios y uso de créditos. Mantener validación local y no reutilizar conclusiones antiguas sobre parámetros como garantías actuales. [Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) |
| OpenAlex | **Mejorar integración existente** | El contrato actual admite consultas públicas sin clave; una clave amplía presupuesto. Recomienda filtrar entidades relacionadas mediante IDs. [API](https://help.openalex.org/api/), [filtros](https://help.openalex.org/api/filtering/) |
| GitHub | **Conservar y mejorar** | Cuota general sin autenticación: 60 solicitudes/hora por IP; autenticación habitual: 5000/hora, con límites adicionales. Token opcional incorporado, sin habilitar lectura de repositorios privados. [Cuotas](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) |
| Crossref | **Siguiente integración académica** | Metadatos de publicaciones y DOI para contrastar autorías y afiliaciones. Añadir después de comprobar aporte único frente a OpenAlex. [REST oficial](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) |
| Bluesky | **Siguiente integración social** | API pública apropiada para perfiles/posts explícitos y paginación acotada. Las operaciones privadas requieren autenticación. Primero medir aporte frente a resultados indexados. [Referencia oficial](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed) |
| Mastodon | **Integración por instancia explícita** | La búsqueda completa de estados depende de backend y autenticación; una instancia no representa toda la federación. [Search](https://docs.joinmastodon.org/methods/search/), [timelines](https://docs.joinmastodon.org/methods/timelines/) |
| YouTube | **API opcional para vídeos y comentarios explícitos** | `commentThreads.list` usa paginación y cuotas; necesita configuración propia. No prometer todos los comentarios de un usuario ni todas las respuestas de un hilo. [Método oficial](https://developers.google.com/youtube/v3/docs/commentThreads/list) |
| Reddit | **Sin colector API nuevo en esta revisión** | El acceso API requiere autorización de la plataforma; no tratar `.json` o un scraper como acceso universal. Las consultas actuales sirven para descubrir menciones indexadas. [Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki) |
| Bing Search | **Retirar de ejecución** | Microsoft retiró las Bing Search APIs el 11 de agosto de 2025. [Anuncio oficial](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement) |

Los nuevos dominios consultados incluyen Stack Overflow, Stack Exchange, Hacker News, Medium, dev.to, Bluesky, Zenodo, Figshare, ALICIA y RENATI. Son consultas de descubrimiento sobre índices web: **no son colectores completos de esas plataformas**. Los extractos pueden mencionar a terceros o una cuenta homónima.

## Arquitectura: qué conservar y qué falta

Conservar `BaseTool`, `ToolRegistry`, el cliente HTTP compartido, los contratos Pydantic, PostgreSQL y la separación entre observación e interpretación. No hace falta reemplazar esto con un framework de agentes ni migrar el grafo a otra base para la feria.

| Prioridad | Trabajo pendiente | Criterio de aceptación |
| --- | --- | --- |
| P0 para publicar o múltiples usuarios | Autenticación de REST, autorización por expediente y límite de trabajos activos | Un usuario no puede leer/eliminar expedientes ajenos. CORS no sustituye autenticación |
| P1 para recuperación real | Cola durable y persistencia incremental de reglas/agente/híbrido | Reiniciar backend durante una búsqueda conserva hallazgos ya obtenidos y reanuda trabajo pendiente sin duplicar gasto |
| P1 para observabilidad | Capabilities/salud por proveedor: configurado, cuota, último error, requisitos de acceso | La interfaz distingue no configurado, bloqueado, sin coincidencias y pendiente |
| P1 para feria | Mostrar cobertura web por ámbito en el workspace | Panel usa `search_coverage`; no presenta intentos como cobertura exhaustiva. El contrato backend ya existe; el panel visual está pendiente |
| P1 para herramientas internas | Unificar el lector explícito de MCP con el registry del agente interno | Agente interno puede pedir lectura dirigida, sin activar rastreo automático ilimitado |
| P2 para documentos | OCR general por páginas y extractores estructurados con ubicación | Una mención conserva número de página/celda/párrafo y método de extracción; las páginas no procesadas quedan explícitas |
| P2 para plataformas | Adaptadores de posts/hilos públicos con cursores y límites | Cada resultado conserva URL, autor declarado, fecha y tipo de relación; pruebas de paginación y controles negativos |
| P2 para escalar SSE | Bus compartido entre workers, por ejemplo Redis | El cliente recibe eventos aunque el trabajo y el stream estén en procesos distintos |
| P2 para costes y latencia | Reservas de cuota por proveedor y caché con TTL y clave del alcance | Dos expedientes simultáneos no superan cuota ni mezclan evidencia o presupuestos |

Una cola durable se puede implementar conservando PostgreSQL para trabajos y checkpoints; Redis solo sería necesario si el diseño seleccionado lo requiere. El despliegue actual debe mantener **un worker** hasta que el bus deje de vivir en memoria. La traza histórica y los cursores MCP ya son una base aprovechable.

## Configuración para la feria

El archivo `.env.example` contiene un perfil de cobertura ampliada. **No se sobrescribió un `.env` existente ni se configuraron credenciales.** Cambios de settings requieren reiniciar el backend.

```dotenv
SEARCH_MAX_QUERIES=20
SEARCH_MAX_QUERIES_PER_ROUND=5
SEARCH_QUERY_CONCURRENCY=3
SEARCH_READ_PAGES=true
SEARCH_MAX_PAGES=3
USERNAME_SCAN_MAX_SITES=3400
USERNAME_SCAN_MAX_ALIASES=3
HTTP_MAX_CONCURRENCY=120
HTTP_MAX_PER_HOST=4
```

Para un primer barrido MCP, mantener `scan_mode="fast"` (200 sitios en el ejemplo); usar `deep` para ampliar cobertura reutilizando la ya registrada. Para una revisión de expediente terminado, el presupuesto adicional sigue siendo `MCP_REVIEW_MAX_QUERIES=3`: no se amplía silenciosamente.

Con cuatro rondas y cinco consultas por ronda, reglas puede ejecutar hasta veinte consultas. Un plan más grande, pivotes tardíos o errores externos pueden dejar ámbitos pendientes. Cada proveedor puede realizar hasta el presupuesto de intentos: veinte consultas no equivalen necesariamente a veinte solicitudes totales ni a veinte créditos si se utilizan respaldos o búsqueda avanzada.

Brave y tokens opcionales se habilitan solo con sus variables. No se comprobaron solicitudes reales contra Brave con una clave durante esta revisión. El sistema sigue usando los proveedores disponibles cuando falta una clave.

## Protocolo de evaluación antes de sustentar

1. Usar casos sintéticos y participantes que hayan autorizado la auditoría; registrar fuentes esperadas por ámbito y fecha.
2. Comparar versiones con los mismos identificadores, presupuesto, país, proveedor y snapshots del catálogo. Las nuevas huellas de configuración distinguen versiones.
3. Medir recursos relevantes únicos, falsos positivos revisados, precisión de detección, recall contra el conjunto conocido, tiempo, errores y consumo real por proveedor.
4. Separar resultados obtenidos por backend, por navegación del cliente MCP y por importación externa. Una importación no mide el coste de haber descubierto su fuente.
5. Ejecutar alias/nombres inexistentes y homónimos; probar dominio parecido, consulta reflejada en URL, cuotas agotadas y PDF sin capa de texto.
6. Hacer una prueba de pausa/reinicio MCP y otra de caída del LLM. La recuperación completa de trabajos tradicionales continúa pendiente, según la tabla anterior.

La demo debe poder explicar para cada observación: qué dato la originó, qué herramienta la encontró, dónde está la evidencia y qué sigue sin comprobarse. Encontrar más URLs no basta para afirmar que mejoró la recuperación de información relevante.

## Validación de esta entrega

- Suite local completa: **520 pruebas pasan; 9 casos de red o base de datos excluidos por la configuración del proyecto**.
- `docker compose --env-file .env.example config --quiet`: válido; no se construyeron ni iniciaron contenedores.
- `git diff --check`: sin errores.
- Las pruebas nuevas cubren rondas sin pivotes, presupuesto cero, cuotas bloqueadas, retos de DuckDuckGo, filtros host/subdominio, extractos Brave, deduplicación de consultas, configuración de consultas internas, autoría OpenAlex por ID, caché GitHub y lectura de un PDF sintético real.
- No se configuraron claves nuevas, no se sobrescribieron `.env` existentes y no se midió recall contra servicios reales. La disponibilidad real y el aporte de cada fuente requieren el protocolo de evaluación anterior.
