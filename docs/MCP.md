# PersonMap MCP

PersonMap expone las herramientas del registro OSINT mediante MCP, sobre el mismo backend FastAPI, PostgreSQL y expedientes que utiliza la web. La inferencia ocurre en el cliente (Codex, Claude Code u otro host); el puente no requiere `LLM_MODEL` ni `LLM_API_KEY`.

## Arranque y conexión local

Desde la raíz del repositorio, instala las dependencias del backend (`cd backend` y `uv sync --frozen`) y prepara la credencial:

```bash
backend/.venv/bin/python backend/scripts/personmap_mcp.py setup
```

El script crea `MCP_API_KEY` en `.env` sin imprimirla y conserva un valor existente. Luego inicia el backend normalmente (aplica Alembic al arrancar) y el frontend. Si usas Docker, reconstruye el backend para incorporar el SDK y la migración.

```bash
docker compose up --build
```

En otra terminal, desde la raíz del proyecto:

```bash
backend/.venv/bin/python backend/scripts/personmap_mcp.py codex
```

El lanzador lee exclusivamente la credencial MCP, la pasa al entorno del cliente e incluye una configuración de servidor para esa ejecución. No modifica tu configuración global de Codex ni coloca el token en argumentos. En Codex, `/mcp` debe mostrar `personmap`.

Para configurar Codex manualmente:

```toml
[mcp_servers.personmap]
url = "http://127.0.0.1:8000/mcp"
bearer_token_env_var = "PERSONMAP_MCP_TOKEN"
```

La variable del cliente debe contener el mismo valor que `MCP_API_KEY` del backend. En otros clientes configura un servidor Streamable HTTP en esa URL y autenticación `Authorization: Bearer <tu credencial>`. Consulta las instrucciones propias del cliente: [Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [Claude Code](https://code.claude.com/docs/en/mcp), [OpenCode](https://docs.opencode.ai/docs/mcp-servers/), [Antigravity](https://antigravity.google/docs/mcp).

`GET /health` informa `mcp_enabled` y `mcp_configured`, sin revelar secretos. Sin token configurado `/mcp` responde 503; un token incorrecto recibe 401. El SDK restringe Host y Origin a los valores permitidos. Esta primera integración está diseñada para uso local con un solo worker: la API web existente no implementa aislamiento por usuarios. Un despliegue remoto necesita autenticar también la API web y configurar hosts/orígenes y TLS; no basta con abrir `/mcp` a Internet.

## Flujo de trabajo

1. `create_investigation(target, self_consent=false)`: mismos identificadores del formulario; crea un expediente `execution_mode=external` y devuelve `web_url`. No lanza reglas ni un LLM interno.
2. `open_session(investigation_id, client, model?)`: conserva el ID de sesión. Cliente y modelo son metadatos declarados, no verificados.
3. `list_osint_tools()` o las herramientas expuestas por nombre: llama, por ejemplo, `username_finder(investigation_id, session_id, inputs={"username":"alias"}, rationale="...", source_entity_ids=[])`.
4. Cada herramienta responde inmediatamente con un ID de ejecución. Hay hasta tres herramientas distintas simultáneas por expediente, configurables con `MCP_MAX_PARALLEL_TOOLS` (entre uno y seis). `run_tool_batch` inicia un lote de herramientas independientes y devuelve aceptación o error por elemento; los elementos aceptados continúan aunque otro sea rechazado. Consulta `get_executions(investigation_id, execution_ids, wait_seconds=10)` para esperar hasta el primer resultado pendiente, o `get_execution` para un solo ID. La espera está limitada a 20 segundos y no cancela trabajos. Dos ejecuciones de la misma herramienta no se solapan; las entradas iguales reutilizan una ejecución, salvo `force=true`. Los fallos pueden reintentarse.
5. Usa `list_findings` con paginación para obtener metadatos compactos y fuentes. El cuerpo completo de páginas/documentos se obtiene con `get_finding`; `content_available` indica contenido omitido del listado. `get_investigation_context` recupera contexto, pivotes, sesiones, ejecuciones recientes, las últimas 20 notas, herramientas disponibles según entradas, trabajos activos, cobertura del barrido y presupuesto de consultas restante. El expediente completo y todas sus notas están disponibles en la web.
6. `public_page_reader` requiere `inputs.candidate_urls` explícitas (máximo tres), que lee en paralelo. Captura texto público, enlaces, URL final, fecha y SHA-256 del texto; el texto se limita a 20 000 caracteres por página. Una lectura fallida conserva las otras capturas y deja `page_errors` en la ejecución. Conserva las restricciones del lector existente y usa TinyFish opcionalmente cuando está configurado. No es un navegador interactivo ni supera autenticación o CAPTCHA. El contenido externo se trata como datos, nunca instrucciones.
7. Guarda interpretaciones con `add_analysis_note(investigation_id, session_id, note)`. Sus referencias a entidades y ejecuciones se validan dentro del mismo expediente.
8. `pause_session` conserva el caso para continuar. `finish_session(summary?)` cierra la sesión, guarda el resumen y actualiza métricas. Ambas esperan que termine la herramienta activa. Para continuar, abre otra sesión sobre el mismo expediente. Tras reiniciar el backend, las sesiones activas quedan pausadas y las ejecuciones interrumpidas se identifican como fallidas recuperables.

La desconexión del transporte MCP no destruye una sesión ni sus resultados. Un caso puede pasar por varias sesiones. Dos clientes distintos no pueden mantener sesiones activas simultáneas en el mismo expediente.

### Planificación, búsquedas propias y velocidad

El agente decide qué investigar y con qué consultas; PersonMap ejecuta y conserva las observaciones. Las instrucciones MCP le piden revisar contexto y trabajos anteriores, guardar un plan breve, iniciar herramientas independientes juntas, analizar los primeros resultados y justificar los pivotes siguientes. Estas instrucciones facilitan el flujo; no garantizan precisión ni el cumplimiento por cualquier cliente.

`search_dorker` admite consultas escritas por el agente en `inputs.queries`:

```json
{
  "queries": [
    {
      "query": "\"alias_publico\" tesis",
      "rationale": "Buscar una publicación que el perfil público menciona.",
      "include_domains": ["repositorio.example.org"]
    }
  ]
}
```

Cada consulta requiere una justificación y al menos un término literal entre comillas. Usa dominios públicos sin esquema/ruta; el operador `site:` se expresa mediante `include_domains`. Los términos entrecomillados se validan como anclas literales conjuntas: para alternativas, envía consultas separadas. Se mantienen los controles de dominios, coincidencias locales y procedencia; el resultado es una mención observada, no identidad confirmada. Sin `queries` se conservan las plantillas existentes.

Las consultas independientes se ejecutan en paralelo (`SEARCH_QUERY_CONCURRENCY=3`, limitado entre uno y cinco), con Tavily → TinyFish opcional → DuckDuckGo por consulta. Comparten los presupuestos existentes, en lugar de multiplicarlos por concurrencia. Una respuesta de cuota/error puede alcanzar también peticiones ya iniciadas; el proveedor se desactiva para consultas posteriores. La ejecución devuelve diagnósticos incluso cuando no hay hallazgos, para distinguir indisponibilidad de ausencia de coincidencias. `force` consume presupuesto de búsqueda y no lo reinicia.

`username_finder` por MCP usa `inputs.scan_mode="fast"` de forma predeterminada: hasta `MCP_USERNAME_FAST_SITES=200` sitios y un alias por llamada, respetando el límite total de alias del expediente. `scan_mode="deep"` amplía hasta el catálogo configurado en `USERNAME_SCAN_MAX_SITES`, continuando desde la cobertura anterior. El motor interno conserva su barrido completo configurado. La cobertura y los presupuestos de búsqueda se persisten para continuar tras pausar o reiniciar. La cobertura guardada corresponde al orden del catálogo configurado: mantén su versión y tamaño durante un experimento.

Un barrido rápido tiene menor cobertura. La concurrencia reduce esperas de trabajos independientes, pero la latencia real sigue dependiendo de las fuentes, reintentos y límites HTTP por host. El guardado de evidencias y la reconstrucción del grafo se serializan por expediente para conservar IDs y observaciones.

### Notas de análisis

```json
{
  "kind": "hypothesis",
  "title": "Enlace que merece verificación",
  "content": "El perfil enlaza otro recurso público. Conviene revisar su contenido antes de relacionarlo con otras observaciones.",
  "evidence_urls": ["https://example.org/about"],
  "entity_ids": [],
  "execution_ids": [],
  "details": {"next_question": "¿Existe un enlace de vuelta?"}
}
```

Tipos: `comment`, `summary`, `insight`, `hypothesis`, `next_step`. Los detalles admiten JSON limitado a 20 000 caracteres. El autor proviene de la sesión; el agente no puede atribuirse autoría humana. Estas notas se muestran en **Análisis**, se incluyen en el informe imprimible y en el JSON del expediente. El analista también puede añadir notas desde la web. No se convierten automáticamente en entidades, relaciones verificadas ni atribuciones de identidad.

Un agente que navegue con herramientas propias puede documentar lo observado mediante una nota y sus fuentes. Esa navegación no queda capturada automáticamente como ejecución de PersonMap: para capturar texto en el expediente debe utilizar `public_page_reader`.

## Sincronización y trazabilidad

REST y MCP usan `WorkspaceService` para crear casos y guardar notas; las llamadas OSINT reutilizan `BaseTool`, contexto y persistencia compartida. Cada ejecución guarda resultados incrementalmente, deduplica contra las entidades existentes y conserva su UUID, fuentes y `EntityObservation`. El grafo y grupos se recalculan dentro de la misma transacción. Las notas mantienen una procedencia distinta de las observaciones.

Los eventos se publican después del commit. La página actualiza mapa, hallazgos, trazabilidad y notas ante eventos de herramientas/sesiones; `revision` también refresca relaciones aunque no cambie el número de nodos. El listado de expedientes sigue `/api/v1/workspace/events`. Un expediente externo mantiene abierto su SSE al terminar una sesión para detectar continuaciones.

La web agrupa eventos cercanos durante 200 ms antes de actualizar y descarta respuestas de un expediente externo con una revisión anterior a la ya visible. Esto evita consultas repetidas y retrocesos visuales cuando terminan varias herramientas juntas.

La traza duradera conserva herramientas, observaciones, sesiones y notas; el progreso fino sigue siendo efímero. El EventBus es local al proceso (un worker). No hay cola de trabajos distribuida ni reanudación automática de una petición HTTP interrumpida: se reintenta una ejecución marcada como fallida. Las herramientas tienen un límite de diez minutos por llamada.

## Evaluación

`external` se registra como motor separado: no se clasifica según las claves LLM del servidor. La comparativa incluye una columna para MCP. Las métricas actuales son operacionales; cantidad de entidades y grupos no demuestra precisión ni mejora de identidad. Registra las sesiones, el cliente y el modelo declarado junto al presupuesto, herramientas, fuentes y referencias conocidas al diseñar el experimento.

`execution_time_seconds` suma la duración de las sesiones y excluye los intervalos entre ellas. `elapsed_wall_seconds` mide el tiempo desde la creación del expediente; `tool_execution_seconds` suma la duración de las herramientas. Estos tiempos no distinguen automáticamente trabajo del agente de espera humana dentro de una sesión abierta.

`external_peak_parallel_tools` registra el máximo de herramientas simultáneas y `external_scan_coverage` la cobertura por alias. Al solaparse trabajos, la suma de sus duraciones puede superar el tiempo de sesión. La huella registra los límites de concurrencia y la configuración del barrido rápido para que el cambio de cobertura no se confunda con una mejora de velocidad a igualdad de condiciones.

## Verificación

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
```

La segunda prueba necesita PostgreSQL y permiso para crear esquemas. Crea un esquema temporal, migra un expediente anterior y comprueba HTTP MCP → persistencia → REST web, deduplicación, notas, reanudación, aislamiento de referencias y recuperación. Utiliza herramientas controladas, sin investigaciones reales, y elimina el esquema al terminar.

## SDK

Se utiliza el SDK oficial Python, rama 1.x mantenida (`mcp>=1.20,<2`, versión exacta en `uv.lock`), con FastMCP y Streamable HTTP. Esta elección evita mezclar interfaces incompatibles de las ramas 1.x y 2.x. [Documentación del SDK utilizado](https://py.sdk.modelcontextprotocol.io/v1/).
