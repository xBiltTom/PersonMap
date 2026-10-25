# PersonMap

PersonMap es una plataforma de auditoría de huella digital basada en fuentes abiertas (OSINT). Organiza recursos públicos, datos observados, procedencia y relaciones documentadas para que una persona analista pueda revisarlos dentro de un expediente.

> PersonMap no determina que una cuenta pertenezca a una persona, no calcula porcentajes de identidad y no sustituye la validación humana. Una relación es evidencia o procedencia documentada, no una atribución automática.

## Qué resuelve

Una auditoría parte de uno o más datos conocidos de forma explícita —por ejemplo, nombre, alias, correo, teléfono, universidad o DNI— y puede ampliar el contexto con pivotes públicos observados. El resultado conserva cuatro cosas distintas:

- **Datos de investigación**: punto de partida introducido para el expediente.
- **Observaciones**: cuentas, perfiles, correos, dominios, documentos y otros recursos públicos encontrados.
- **Relaciones documentadas**: enlaces explícitos, correos declarados compartidos, menciones u otra evidencia registrada.
- **Procedencia y trazabilidad**: herramienta, momento y ejecución que produjo una observación.

No construye una biografía de una persona ni usa el grafo para fingir causalidad de ejecución.

## Interfaz de trabajo

La aplicación está organizada alrededor de expedientes:

| Vista | Pregunta que responde |
| --- | --- |
| **Inicio** | Alcance del proyecto y acceso a los módulos principales. |
| **Nueva auditoría** | Registra el objetivo, datos conocidos y estrategia de exploración. |
| **Expedientes** | Lista las auditorías ejecutadas, su estado y acceso a cada caso. |
| **Mapa digital** | ¿Qué observaciones están conectadas por evidencia o procedencia documentada? |
| **Hallazgos** | ¿Qué información concreta se extrajo de cada recurso? |
| **Trazabilidad** | ¿Cómo llegó el motor a los hallazgos durante la ejecución? |
| **Consola** | ¿Qué está ocurriendo operativamente en tiempo real? |

Dentro de un expediente, el inspector lateral reutiliza la misma normalización de datos para nodos del mapa, filas de Hallazgos y observaciones de Trazabilidad. Solo muestra secciones que contienen datos reales: campos observados, descripciones, enlaces, artefactos visuales, relaciones y procedencia.

## Mapa digital y relaciones

El mapa usa nodos reales persistidos en el expediente y distingue visualmente dos clases de aristas:

- **Objetivo → hallazgo**: procedencia o contexto. Explica por qué un recurso apareció relacionado con los datos de partida; no demuestra pertenencia.
- **Hallazgo → hallazgo**: evidencia observada entre recursos, como un enlace explícito o un correo declarado compartido.

Las aristas de procedencia son menos prominentes. Las relaciones entre hallazgos se inspeccionan con su tipo, evidencia disponible y fuente. El mapa permite buscar, filtrar capas, relaciones y evidencia, enfocar nodos, usar MiniMap, exportar JSON y GraphML, y navegar desde Hallazgos hacia el nodo correspondiente.

## Hallazgos

Hallazgos es la vista de revisión tabular del expediente. Para cada recurso muestra, cuando existe:

- plataforma, tipo de entidad, identificador y enlace original;
- señales de datos extraídos, como bio, correo, avatar, enlaces, universidad o ubicación;
- relaciones reales recibidas desde el mismo grafo del mapa;
- herramienta y procedencia;
- acciones para inspeccionar el recurso, abrir la fuente pública o ubicarlo en el mapa.

No muestra estados de confianza ni etiquetas de atribución automática.

## Trazabilidad persistida

Trazabilidad no reutiliza las relaciones del mapa como si fueran causalidad. Conserva una traza estructurada de la ejecución para que una investigación terminada pueda revisarse aun después de reiniciar el backend:

- `ToolExecution`: ejecución concreta de una herramienta, capa/motor, ronda o turno, inicio, fin, estado y cantidad de observaciones.
- `EntityObservation`: observación de una entidad canónica por una ejecución concreta. Una entidad deduplicada puede conservar múltiples observaciones de distintas herramientas.
- `InvestigationTraceEvent`: eventos estructurales como inicio de motor, rondas, turnos, pivotes, refinamiento y llamadas omitidas.

La vista ofrece árbol expandible, cronología sobre la misma traza, filtros, búsqueda, métricas derivadas de datos reales e inspector contextual. Los expedientes anteriores a esta persistencia se identifican explícitamente como históricos limitados; no se les inventa una cadena causal retrospectiva.

## Consola operacional

La consola combina dos fuentes con responsabilidades distintas:

- **EventBus + SSE**: stream operacional efímero para progreso, reconexión y eventos en vivo.
- **Trace DB**: fuente histórica durable de herramientas, tiempos, errores estructurados, rondas, turnos, pivotes y observaciones.

Al abrir un expediente, la consola indica si está `EN VIVO`, si conserva un `REGISTRO COMPLETO` del EventBus, si muestra un `HISTORIAL RECONSTRUIDO` desde trazabilidad o si el expediente solo tiene historial limitado. El modo reconstruido no intenta recrear progreso transitorio.

Incluye búsqueda local, filtros por tipo y capa, resumen compacto de tools/errores/pivotes/tiempo, seguimiento automático con contador de eventos nuevos, detalle controlado de errores y acciones para copiar o exportar el registro visible. Las herramientas pueden incluir duración y su `tool_execution_id` para enlazar con Trazabilidad.

## Motores de exploración

PersonMap conserva tres estrategias independientes:

- **Reglas (`rule_based`)**: barrido heurístico determinista con rondas y pivotes controlados.
- **Agente (`agentic`)**: herramientas seleccionadas mediante function calling cuando hay un modelo LLM configurado.
- **Híbrido (`hybrid`)**: ejecuta primero el barrido heurístico y usa IA solo para cubrir huecos, sin repetir llamadas ya cubiertas.

La IA es opcional. Sin `LLM_MODEL` y `LLM_API_KEY`, el motor de reglas sigue funcionando. El uso de IA no convierte un hallazgo en una conclusión de identidad.

## Herramientas e integraciones OSINT

Las estrategias de exploración coordinan las herramientas según los datos disponibles, el alcance elegido y los presupuestos de cada investigación. PersonMap combina bibliotecas originales, catálogos de detección, técnicas adaptadas y módulos propios que consultan fuentes públicas.

### Integraciones principales

| Integración | Qué aporta | Cómo se integra y qué requiere |
| --- | --- | --- |
| **[Maigret](docs/MAIGRET.md)** | Búsqueda de cuentas por alias, consultas por identificadores tipados, extracción, enriquecimiento e informes. | Biblioteca original en procesos aislados, utilizada por `username_finder` y `maigret_enricher`. El alcance, los filtros y los servicios opcionales se configuran en PersonMap. |
| **[WhatsMyName](docs/WHATSMYNAME.md)** | Recetas de detección de cuentas por alias que complementan las comprobaciones de Maigret. | Dataset y recetas ejecutados por `username_finder`, incluidos métodos HTTP, cabeceras y firmas de presencia/ausencia. Los catálogos se conservan separados y se combinan durante el escaneo. |
| **[Holehe — técnicas adaptadas](docs/HOLEHE.md)** | Sondas de registro de correo en servicios, con controles negativos y estados por consulta. | `email_enumerator` adapta consultas y validaciones de Holehe y añade sondas propias. Se ejecutan con asyncio/HTTPX de PersonMap; el paquete y la CLI de Holehe no se instalan. |
| **[GHunt](docs/GHUNT.md)** | Consulta de perfiles Google y datos expuestos de servicios como Maps, Calendar, Play Games y recursos públicos de Drive/Docs, según la entrada y el alcance implementado. | `ghunt` usa la biblioteca original en un entorno Python independiente. Requiere habilitar la integración, instalar su runtime y configurar la sesión del operador. Scholar y YouTube tienen búsquedas públicas complementarias en `google_account_osint`. |

### Módulos propios y fuentes consultadas

| Área / herramientas | Fuentes y función | Configuración y documentación |
| --- | --- | --- |
| **Búsqueda web** — `search_dorker` | Consultas y dorks mediante Tavily, TinyFish, Brave o DuckDuckGo, con lectura acotada de páginas y documentos públicos. | Los proveedores con API requieren sus claves; la selección y los respaldos dependen de la configuración. [Motor de búsqueda](docs/MOTOR_BUSQUEDA.md). |
| **Huella académica** — `academic_finder`, `google_account_osint` | Publicaciones y autores de OpenAlex/Crossref; perfiles públicos de Scholar y candidatos de YouTube. | Clave de OpenAlex y contacto Crossref configurables; cada proveedor conserva su estado y procedencia. [Motor académico](docs/ACADEMICO.md) y [Google público](docs/HOLEHE.md#github-y-google-públicos). |
| **Correo y Gravatar** — `email_checker`, `gravatar_deep` | Clasificación del dominio del correo, coincidencias exactas con correos públicos en GitHub y datos publicados en perfiles Gravatar. | Requieren un correo de entrada u observado. [Correo](docs/HOLEHE.md) y [registro de fuentes](docs/OSINT_SOURCES.md). |
| **GitHub** — `github_deep_scanner` | Perfil, repositorios, actividad y metadatos públicos asociados al alias consultado. | `GITHUB_API_TOKEN` es opcional y amplía el margen de consultas. [Registro de fuentes](docs/OSINT_SOURCES.md). |
| **Keybase y Wikipedia** — `keybase_resolver`, `wikipedia_edits` | Enlaces y pruebas publicados en Keybase; contribuciones públicas por alias mediante la API de MediaWiki. | Consultas a APIs públicas. [Registro de fuentes](docs/OSINT_SOURCES.md). |
| **Perfiles sociales** — `social_url_extractor`, `social_verifier` | Reconocimiento de URLs candidatas y extracción de metadatos observados de perfiles públicos. | La disponibilidad depende de cada plataforma; se conserva el estado de verificación. [Redes sociales](docs/AUDITORIA_REDES_SOCIALES_2026-10-07.md) y [Telegram](docs/AUDITORIA_TELEGRAM_2026-10-07.md). |
| **Dominios** — `domain_finder` | Dominios y subdominios observados en registros públicos de Certificate Transparency mediante crt.sh. | Parte de dominios explícitos o derivados de los datos de entrada. [Registro de fuentes](docs/OSINT_SOURCES.md). |
| **Teléfonos** — `phone_lookup` | Normalización y análisis del plan de numeración con `phonenumbers`, con consulta de red opcional. | El formato válido y el operador original no confirman actividad ni titularidad. [Motor telefónico](docs/AUDITORIA_TELEFONOS_2026-10-07.md). |
| **DNI y documentos** — `dni_lookup` | Menciones de DNI en páginas y datasets públicos, con lectura de documentos y OCR cuando corresponde. | Fuentes explícitas/configuradas y OCR local. [DNI](docs/AUDITORIA_DNI_2026-10-07.md) y [OCR de PDF](docs/OCR_PDF.md). |
| **Brechas e infostealers** — `breach_checker`, `infostealer_checker` | Reportes de exposición de XposedOrNot y Hudson Rock Cavalier. | La consulta de infostealers requiere consentimiento explícito y conserva solo los campos permitidos por el módulo. [Registro de fuentes](docs/OSINT_SOURCES.md). |
| **Búsqueda inversa de imágenes** — `reverse_image_search` | Búsqueda de imágenes a partir de URLs de avatares observados mediante Google Lens vía SerpAPI. | Opcional; requiere `SERPAPI_KEY`. [Registro de fuentes](docs/OSINT_SOURCES.md). |

La ejecución de cada herramienta depende de sus entradas y requisitos; una integración disponible en el código puede estar deshabilitada o carecer de credenciales en una instalación concreta. Los resultados conservan su procedencia y los estados de consulta. El [registro de fuentes y técnicas OSINT](docs/OSINT_SOURCES.md) detalla la procedencia y las referencias de las integraciones.

## Agentes externos mediante MCP

El backend también expone `/mcp` para que Codex, Claude Code u otros clientes compatibles dirijan las herramientas sobre los mismos expedientes de la web. El modo externo no depende de las claves LLM del servidor: guarda resultados por ejecución, conserva sesiones para continuar un caso y sincroniza mapa, hallazgos, trazabilidad y análisis mediante SSE.

El cuaderno de **Análisis** permite persistir comentarios, resúmenes, hallazgos destacados, hipótesis y próximos pasos con fuentes y referencias. El lector de páginas públicas guarda texto y enlaces que un agente puede analizar. Las interpretaciones del agente se conservan como notas, separadas de las observaciones y relaciones documentadas.

El agente puede escribir consultas propias con justificación y filtros de dominio, iniciar hasta tres herramientas independientes juntas y consultar sus estados en una sola llamada. El barrido MCP empieza con un modo rápido de hasta 200 sitios por alias; el modo profundo continúa desde la cobertura guardada. Los presupuestos y la cobertura sobreviven a una pausa o reinicio, y los listados compactos dejan el texto completo para la lectura de hallazgos individuales.

Consulta [la guía de conexión y uso de MCP](docs/MCP.md) para preparar la credencial local, conectar clientes y ejecutar las pruebas.

La [política de correlación y cercanía visual](docs/CORRELACION.md) explica las señales de correo y teléfono, los vecindarios del mapa y sus límites: la cercanía ordena candidatos y no confirma pertenencia.

## Fuentes y artefactos públicos

La [auditoría de cobertura y arquitectura del 12-10-2026](docs/AUDITORIA_OSINT_2026-10-12.md) documenta las mejoras del buscador, el inventario de herramientas, las fuentes evaluadas y el trabajo pendiente para la feria. `SEARCH_MAX_QUERIES` define un presupuesto independiente del proveedor (el ejemplo usa 20); MCP y los agentes reciben `search_coverage` con consultas intentadas y ámbitos pendientes. Brave es un respaldo opcional y el lector público admite PDFs con capa de texto. Los ámbitos consultados no equivalen a cobertura exhaustiva de una plataforma.

El registro de herramientas cubre, según los datos de entrada y la disponibilidad pública, búsqueda de aliases, perfiles sociales, cuentas de desarrollo, correo, Gravatar, dominio, documentos académicos, teléfonos, dorks, brechas, infraestructura y verificaciones de URLs públicas.

Cuando una fuente ya devuelve datos como `avatar_url`, perfiles asociados, OpenGraph o thumbnails, PersonMap los persiste como artefactos visuales observados y puede mostrarlos en el inspector. No realiza reconocimiento facial, matching biométrico ni afirma identidad a partir de imágenes. La búsqueda inversa de imagen es opcional y requiere una clave configurada.

Las herramientas respetan sus condiciones de ejecución: no deben usarse para evadir autenticación, CAPTCHAs, paywalls o controles de acceso. Revisa las obligaciones legales, las condiciones de las fuentes y el consentimiento aplicable antes de auditar datos de terceros.

## Arquitectura

```text
person-map/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Investigaciones, grafo, stream, métricas y encuestas
│   │   ├── agent/           # Agente LLM opcional y despacho de herramientas
│   │   ├── engine/          # Reglas, motor híbrido, persistencia, pivotes y trace
│   │   ├── models/          # SQLAlchemy: entidades, relaciones y traza persistida
│   │   ├── schemas/         # Contratos Pydantic de API
│   │   └── tools/           # Herramientas OSINT sobre fuentes públicas
│   ├── migrations/          # Historial Alembic
│   └── tests/               # Pruebas de motores, persistencia y contratos
├── frontend/
│   └── src/
│       ├── app/             # Inicio, auditorías, expedientes y workspace
│       ├── components/      # Mapa, inspector, hallazgos, trazabilidad y consola
│       ├── context/         # Estado de navegación del workstation
│       └── lib/             # API, tipos y normalizadores compartidos
├── docker-compose.yml
├── .env.example
└── README.md
```

### Flujo de datos

```text
Herramientas públicas
        │
        ├── EventBus / SSE ──────────────► Consola en vivo
        │
        └── Persistencia
              ├── Entity + Relationship ─► Mapa digital / Hallazgos
              └── ToolExecution + EntityObservation + TraceEvent
                                          └► Trazabilidad / historial reconstruido
```

## Ejecución con Docker Compose (Recomendado)

La forma más rápida de levantar toda la plataforma (PostgreSQL 16, backend con migraciones automáticas y frontend optimizado):

```bash
# 1. Configurar variables de entorno (claves de API opcionales)
cp .env.example .env

# 2. Construir e iniciar todos los servicios
docker compose up --build
```

- **Frontend**: `http://localhost:3000`
- **Backend API**: `http://localhost:8000/api/v1`
- **OpenAPI / Swagger**: `http://localhost:8000/docs`
- **Health check**: `http://localhost:8000/health`

Para detener los servicios:
```bash
docker compose down
# O para reiniciar descartando el volumen de base de datos:
docker compose down -v
```

## Requisitos para desarrollo local manual

- PostgreSQL 16 o superior.
- Python 3.12 o superior y [`uv`](https://docs.astral.sh/uv/).
- Node.js 20 o superior y `pnpm` (el proyecto fija `pnpm@11.5.2`).

## Ejecución local (Desarrollo manual)

### 1. Configurar entorno

```bash
cp .env.example .env
```

Edita al menos `DATABASE_URL` si tu PostgreSQL no usa el valor local por defecto. `LLM_MODEL`, `LLM_API_KEY`, `TAVILY_API_KEY`, `TINYFISH_API_KEY`, `BRAVE_API_KEY`, `OPENALEX_API_KEY`, `GITHUB_API_TOKEN` y `SERPAPI_KEY` son opcionales. Bing Search fue retirado y su clave ya no activa búsquedas.

### 2. Crear la base de datos

```bash
createdb -U postgres person_map
```

Las migraciones Alembic se aplican al iniciar el backend. Para ejecutarlas explícitamente:

```bash
cd backend
uv run alembic upgrade head
```

### 3. Iniciar backend

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://localhost:8000/api/v1`
- OpenAPI: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

Para que la consola SSE funcione correctamente en desarrollo, usa un solo worker: el EventBus actual vive dentro del proceso.

### 4. Iniciar frontend

En otra terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

Abre `http://localhost:3000`.

## API principal

| Método | Ruta | Uso |
| --- | --- | --- |
| `POST` | `/api/v1/investigations` | Crea y lanza una auditoría. |
| `GET` | `/api/v1/investigations` | Lista expedientes. |
| `GET` | `/api/v1/investigations/{id}` | Obtiene el expediente y sus entidades. |
| `GET` | `/api/v1/investigations/{id}/graph` | Grafo factual de observaciones y relaciones. |
| `GET` | `/api/v1/investigations/{id}/graphml` | Exportación GraphML. |
| `GET` | `/api/v1/investigations/{id}/trace` | Trazabilidad estructurada persistida. |
| `GET` | `/api/v1/investigations/{id}/logs` | Registro original, reconstruido o legacy. |
| `GET` | `/api/v1/investigations/{id}/stream` | Stream SSE de la ejecución activa. |
| `DELETE` | `/api/v1/investigations/{id}` | Elimina el expediente y sus datos asociados. |

## Validación y calidad

```bash
# Backend
cd backend
uv run pytest

# Frontend
cd frontend
pnpm lint
pnpm build
```

Las pruebas de backend excluyen por defecto casos que requieren red o PostgreSQL. Consulta los marcadores definidos en `backend/pyproject.toml` para ejecutar esos grupos de forma explícita.

## Límites y consideraciones

- Los resultados dependen de fuentes públicas, disponibilidad externa y datos de entrada; una ausencia no prueba inexistencia.
- Las entidades se deduplican, pero sus observaciones por herramienta se preservan para trazabilidad.
- Los enlaces e imágenes externas se tratan como recursos no confiables y se presentan como evidencia pública, no como contenido ejecutable.
- Los datos iniciales del objetivo se distinguen de la evidencia recuperada externamente.
- El análisis, interpretación y cualquier atribución final corresponden a una revisión humana responsable.
