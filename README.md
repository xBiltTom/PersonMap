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

## Fuentes y artefactos públicos

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

## Requisitos

- PostgreSQL 16 o superior.
- Python 3.12 o superior y [`uv`](https://docs.astral.sh/uv/).
- Node.js 20 o superior y `pnpm` (el proyecto fija `pnpm@11.5.2`).

## Ejecución local

### 1. Configurar entorno

```bash
cp .env.example .env
```

Edita al menos `DATABASE_URL` si tu PostgreSQL no usa el valor local por defecto. `LLM_MODEL`, `LLM_API_KEY`, `TAVILY_API_KEY`, `SERPAPI_KEY` y `BING_VISUAL_SEARCH_KEY` son opcionales.

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
