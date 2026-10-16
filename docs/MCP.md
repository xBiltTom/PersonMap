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
7. En investigaciones Fair con Verification Gate finalizado, `prepare_exposure_analysis(investigation_id, max_posts=8, candidate_limit=24)` devuelve una muestra acotada de publicaciones minimizadas, la priorización por reglas locales y los enlaces entre cuentas. No llama a Google AI Studio ni a otro LLM del servidor, y no reemplaza ni persiste sobre el informe web. El agente puede seleccionar los posts de más riesgo con su propio modelo, reconstruir la huella y guardar la lectura con fuentes mediante `add_analysis_note`.
8. Guarda interpretaciones con `add_analysis_note(investigation_id, session_id, note)`. Sus referencias a entidades y ejecuciones se validan dentro del mismo expediente.
9. `pause_session` conserva el caso para continuar. `finish_session(summary?)` cierra la sesión, guarda el resumen y actualiza métricas. Ambas esperan que termine la herramienta activa. Para continuar, abre otra sesión sobre el mismo expediente. Tras reiniciar el backend, las sesiones activas quedan pausadas y las ejecuciones interrumpidas se identifican como fallidas recuperables.

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

### Investigación autónoma y evidencia del navegador

El flujo principal del agente externo parte de los identificadores iniciales; no requiere ejecutar antes un barrido tradicional. Las instrucciones MCP orientan al agente a formular hipótesis, elegir pocas consultas útiles, variar el nombre con prudencia, explorar documentos y fuentes institucionales, contrastar resultados y detener vías sin evidencia nueva. Se recomienda navegación y búsqueda propias del cliente cuando estén disponibles, utilizando las herramientas PersonMap según las necesidades y el presupuesto. El servidor no invoca otro LLM ni proporciona un navegador al cliente.

El prompt MCP `investigate_person(investigation_id, objective, max_external_searches=6)` ofrece ese flujo. Su límite de búsquedas externas es una instrucción orientativa: el servidor no puede controlar llamadas del navegador del cliente. Las instrucciones generales también se entregan al conectar, aunque el cliente no exponga prompts MCP. Una petición normal puede ser: «Investiga este caso desde cero, combina tu navegación con PersonMap, persiste evidencia con fuentes y contrasta las hipótesis antes de concluir».

`import_external_evidence(investigation_id, session_id, batch)` guarda hasta diez observaciones por lote, dentro de un expediente externo con sesión activa:

```json
{
  "rationale": "El documento publica el nombre con apellidos primero",
  "idempotency_key": "document-roll-reading-001",
  "records": [{
    "entity_type": "document",
    "url": "https://example.org/roll",
    "source_url": "https://example.org/roll",
    "title": "Padrón académico",
    "acquisition_method": "agent_browser",
    "evidence_level": "page_content",
    "observed_at": "2026-10-12T12:00:00Z",
    "excerpt": "PÉREZ ROJAS ANA MARÍA — Ingeniería",
    "locator": "Página 22, fila correspondiente",
    "identifiers": [{"kind": "name", "value": "Pérez Rojas Ana María"}]
  }]
}
```

Usa la fecha real de lectura con zona horaria; la fecha del ejemplo es ilustrativa. `agent_browser` corresponde a `page_content`; `agent_search` a `search_result`. En este último caso no se admiten identificadores ni enlaces como hechos extraídos de una página. Las URL deben ser públicas y los identificadores declarados deben aparecer completos en el extracto. Si la URL del recurso difiere de la fuente, debe aparecer en el extracto. Los enlaces declarados también requieren presencia textual. El contrato permite documento, página, perfil candidato y mención de búsqueda, sin campos libres para inventar verificación, confianza o procedencia de otra herramienta.

El servidor **no descarga ni verifica** estas fuentes: conserva lo que declara el cliente. Los registros mantienen método, autor, sesión, fecha, extracto, ubicación y UUID de observación dentro de `external_reports`. Se deduplican entidades, conservando observaciones distintas y sus extractos. Aparecen en mapa, grupos, inspector, REST y actualizaciones incrementales. El inspector muestra las cinco lecturas externas más recientes; `get_finding` devuelve el historial completo. Las lecturas de buscador y de página permanecen diferenciadas aunque correspondan a la misma URL.

`get_investigation_context.reported_candidates` ofrece identificadores declarados con su entidad y fuente. No se convierten automáticamente en semillas ni relaciones de identidad: el agente selecciona explícitamente el siguiente pivote y cita su entidad de origen. Los enlaces declarados tampoco se incorporan automáticamente como conexiones verificadas. Las correlaciones se evalúan mediante `add_correlation_assessment`, conservando incertidumbre y revisión.

Repetir el mismo lote reutiliza su importación. Una `idempotency_key` fija admite reintentos del mismo contenido; reutilizarla con contenido diferente devuelve 409. Cada lote es atómico y valida referencias del mismo expediente. La sesión debe seguir activa incluso al reutilizar un lote.

La traza identifica `external_evidence_import`, con duración **solo de persistencia**. `tools_executed` y `tool_execution_seconds` siguen contando herramientas recolectoras; `external_import_batches`, `external_import_observations` y `external_import_seconds` contabilizan importaciones por separado. El tiempo/coste de navegación externa no se infiere de la importación (`external_acquisition_time_measured=false`); debe declararse en el registro de búsqueda del agente y en el protocolo de evaluación.

### Cobertura documental y navegación del agente

El barrido de búsqueda reserva una consulta documental en una ronda inicial de al menos cinco consultas, sin aumentar el presupuesto total. Incluye Scribd, SlideShare, Studocu y College Sidekick. La búsqueda general del nombre no exige que el documento contenga literalmente la universidad; esa combinación queda como consulta secundaria.

Para nombres de cuatro a seis palabras se prueba también el orden con las últimas dos palabras primero. Es una alternativa de búsqueda acotada, no una descomposición verificada de nombres y apellidos. Las consultas documentales usan alternativas de frases completas; su validación admite mayúsculas, tildes, separadores y apellidos primero. Se conservan `matched_name_variant`, `document_candidate` y atribución sin verificar. Las consultas propias del agente mantienen sus anclas independientes como AND: debe enviar consultas separadas para las alternativas.

`get_investigation_context` devuelve `name_search_variants`. Los diagnósticos del buscador incluyen resultados recibidos y rechazos por falta de evidencia literal, dominio incorrecto o URL insegura. Si el proveedor no devuelve un documento o el fragmento no muestra el nombre, no se puede concluir que no exista.

La lectura opcional de resultados (`SEARCH_READ_PAGES=true`) también admite plataformas documentales; conserva los límites de páginas. El lector nativo y `public_page_reader` buscan el nombre completo dentro del contenido público leído y guardan un extracto acotado, incluso si aparece después de los primeros 20 000 caracteres. Se mantienen límites de descarga y tiempo, y se descartan enlaces de navegación, cabecera y pie antes de recoger enlaces del contenido. Sitios que requieren autenticación, contenido no accesible o límites de tamaño pueden impedir la captura.

El agente puede complementar MCP con su navegador y buscador propios. Debe guardar fuentes y distinguir búsqueda indexada, texto leído, candidatura y conclusiones mediante notas. Esa navegación no se registra automáticamente como ejecución PersonMap: usa `public_page_reader` para capturas compatibles, o declara en la nota el método externo. Para el artículo, evalúa «agente con navegación ampliada» como una capacidad adicional; no mezcles sus resultados con el piloto restringido a herramientas compartidas.

### Lectura incremental para agentes

Tras leer el contexto inicial con `get_investigation_context`, conserva `investigation.revision` y pagina los hallazgos iniciales con `list_findings`. Después usa una sola llamada para obtener cambios:

```json
{
  "investigation_id": "UUID-del-expediente",
  "since_revision": 3,
  "limit": 20,
  "wait_seconds": 10
}
```

La herramienta `get_workspace_updates` devuelve `changes` de tipo `state`, `execution`, `finding` y `note`. Incluye tanto entidades nuevas como entidades existentes que recibieron otra observación. Las páginas contienen hasta 50 registros de cambio; notas resumidas y hallazgos sin el texto completo de páginas. Para leer ese texto utiliza `get_finding`; las notas completas siguen disponibles en el contexto y la web.

Conserva `next_cursor` y pásalo como `cursor` en las siguientes llamadas (manteniendo `since_revision`; el cursor tiene prioridad). Si `has_more=true`, termina de leer las páginas antes de esperar. Una revisión puede abarcar varias páginas: avanzar directamente a `revision` omitiría registros pendientes. Los registros muestran los datos actuales de cada objeto, por lo que una entidad o ejecución puede aparecer más de una vez con el mismo ID.

El cursor pertenece a un expediente y persiste entre reinicios. Los cambios se guardan en la misma transacción que sus resultados y se leen en orden de revisión. La espera solo se aplica si no hay cambios disponibles y hay herramientas activas en este proceso, con un máximo de 20 segundos; no cancela tareas. Las consultas y el presupuesto OSINT permanecen iguales.

Esta lectura está disponible para expedientes externos y registra cambios posteriores a esta versión. Para expedientes preexistentes o revisiones importadas, lee primero el contexto y los hallazgos iniciales. El registro incremental no reconstruye su historial anterior. `run_tool_batch` ya permite lanzar herramientas independientes en una petición; ahora la lectura incremental reúne sus resultados, estados y notas en otra petición, evitando consultar cada ejecución y después volver a listar todos los hallazgos.

REST y MCP usan `WorkspaceService` para crear casos y guardar notas; las llamadas OSINT reutilizan `BaseTool`, contexto y persistencia compartida. Cada ejecución guarda resultados incrementalmente, deduplica contra las entidades existentes y conserva su UUID, fuentes y `EntityObservation`. El grafo y grupos se recalculan dentro de la misma transacción. Las notas mantienen una procedencia distinta de las observaciones.

Los eventos se publican después del commit. La página actualiza mapa, hallazgos, trazabilidad y notas ante eventos de herramientas/sesiones; `revision` también refresca relaciones aunque no cambie el número de nodos. El listado de expedientes sigue `/api/v1/workspace/events`. Un expediente externo mantiene abierto su SSE al terminar una sesión para detectar continuaciones.

La web agrupa eventos cercanos durante 200 ms antes de actualizar y descarta respuestas de un expediente externo con una revisión anterior a la ya visible. Esto evita consultas repetidas y retrocesos visuales cuando terminan varias herramientas juntas.

La traza duradera conserva herramientas, observaciones, sesiones y notas; el progreso fino sigue siendo efímero. El EventBus es local al proceso (un worker). No hay cola de trabajos distribuida ni reanudación automática de una petición HTTP interrumpida: se reintenta una ejecución marcada como fallida. Las herramientas tienen un límite de diez minutos por llamada.

## Evaluación

### Pivotes y evaluaciones de correlación

Las **ejecuciones nuevas** sobre una revisión importada requieren `rationale`, `source_entity_ids` y un plan `pivot`; también los refrescos con `force`. Las ejecuciones idénticas reutilizadas conservan el registro original. En expedientes externos creados desde cero el plan es opcional, pero si se proporciona necesita entidades de origen y una justificación.

```json
{
  "question": "¿El portafolio enlaza de vuelta al perfil observado?",
  "expected_signal": "Un enlace público al mismo perfil",
  "stop_condition": "Detener esta vía tras revisar la página y sus enlaces directos"
}
```

El plan se guarda en la ejecución y se muestra en la trazabilidad. El servidor valida la estructura y que los hallazgos de origen pertenezcan al expediente; evaluar la evidencia y cumplir la condición de parada corresponde al agente. No verifica automáticamente que un alias nuevo sea una deducción correcta.

`add_correlation_assessment(investigation_id, session_id, assessment)` registra una hipótesis estructurada con al menos dos entidades distintas, `reasoning`, `verdict` y fuentes `supporting_urls` / `contradicting_urls`. Los veredictos admitidos son `candidate`, `supported`, `refuted` e `inconclusive`. `supported` exige fuentes a favor y `refuted` fuentes en contra. `execution_ids` permite enlazar las herramientas utilizadas. Las referencias deben pertenecer al mismo expediente.

Para revisar una evaluación, proporciona `supersedes_note_id` y las mismas entidades: se crea otra nota conservando intactas la anterior y su autoría. Las evaluaciones aparecen como hipótesis en **Análisis**, con el veredicto y sus detalles; también llegan en la lectura incremental. Son interpretaciones del agente y no modifican automáticamente relaciones, grupos ni atribuciones de identidad. Las fuentes se validan como URLs públicas; su pertinencia y contenido requieren revisión.

### Revisar un barrido tradicional

`create_review_investigation(source_investigation_id)` copia un expediente interno **terminado por reglas** a uno externo nuevo. Conserva entidades, observaciones, ejecuciones y referencias del grafo, enlaza el original y devuelve la URL web. El original permanece intacto. Abre una sesión sobre el ID nuevo, consulta `get_investigation_context` y `list_findings`, y utiliza las notas para distinguir evidencia, hipótesis y conclusiones.

Los nuevos barridos guardan cobertura reutilizable. La revisión solo hereda cobertura de alias cuando coincide la configuración del catálogo; expedientes antiguos o incompatibles devuelven `coverage_known=false`. No se reconstruye cobertura a partir del número de perfiles encontrados. Las llamadas idénticas con huella guardada reutilizan ejecuciones; una herramienta ya ejecutada requiere entradas explícitas para una subbúsqueda o un refresco deliberado con `force`.

`MCP_REVIEW_MAX_QUERIES=3` limita las consultas **adicionales**, sin superar `TAVILY_MAX_QUERIES`; cero permite revisión sin nuevas consultas de buscador. Las instrucciones recomiendan como máximo dos rondas enfocadas, sin imponer ese límite en el servidor. Las métricas separan ejecuciones heredadas (`imported_executions`), hallazgos importados y herramientas nuevas; `review_baseline` conserva las métricas del original. Para comparar esta condición con reglas, contabiliza el barrido más la revisión y su presupuesto adicional.

Ejemplo de petición al agente: «Revisa el expediente UUID mediante `create_review_investigation`. Lee primero los hallazgos, realiza hasta dos rondas de subbúsquedas justificadas y guarda un resumen con fuentes y dudas pendientes».

Las optimizaciones compartidas exigen contexto de documento para coincidencias numéricas en texto libre; un número exacto aislado ya no basta. Los campos estructurados de DNI siguen siendo válidos. Los dominios proceden de correos, enlaces publicados por perfiles observados o una selección explícita del agente; las URLs genéricas del buscador no se convierten en infraestructura personal. Cada dominio se consulta una vez por contexto, hasta cuatro, y su propiedad permanece sin verificar.

`external` se registra como motor separado: no se clasifica según las claves LLM del servidor. La comparativa incluye una columna para MCP. Las métricas actuales son operacionales; cantidad de entidades y grupos no demuestra precisión ni mejora de identidad. Registra las sesiones, el cliente y el modelo declarado junto al presupuesto, herramientas, fuentes y referencias conocidas al diseñar el experimento.

`execution_time_seconds` suma la duración de las sesiones y excluye los intervalos entre ellas. `elapsed_wall_seconds` mide el tiempo desde la creación del expediente; `tool_execution_seconds` suma la duración de las herramientas. Estos tiempos no distinguen automáticamente trabajo del agente de espera humana dentro de una sesión abierta.

`external_peak_parallel_tools` registra el máximo de herramientas simultáneas y `external_scan_coverage` la cobertura por alias. Al solaparse trabajos, la suma de sus duraciones puede superar el tiempo de sesión. La huella registra los límites de concurrencia y la configuración del barrido rápido para que el cambio de cobertura no se confunda con una mejora de velocidad a igualdad de condiciones.

### Comparación con la ejecución tradicional optimizada

El motor de reglas ya despacha las herramientas disponibles en paralelo por ronda; ambos caminos comparten la implementación OSINT, los límites HTTP y las consultas paralelas de `search_dorker`. La concurrencia de herramientas no es idéntica: las reglas despachan la ronda completa y MCP limita los trabajos simultáneos por expediente. Registra esta diferencia al interpretar tiempos. Las optimizaciones compartidas deben estar presentes en ambos caminos antes de medir.

Para estudiar el aporte de la planificación del agente, prepara expedientes nuevos y separados con los mismos datos iniciales, consentimiento, versión del código, catálogo, proveedores y configuración de presupuestos. Ejecuta las condiciones por separado, alternando su orden entre repeticiones, para reducir competencia por conexiones y efectos del orden sobre cuotas y disponibilidad. Conserva también los fallos y ejecuciones incompletas.

- **Cobertura del barrido:** pide al agente `scan_mode="deep"` desde el inicio para usar el mismo máximo de sitios que la ejecución interna. Compara la cobertura efectivamente realizada y los alias comprobados; compartir un máximo no implica haber examinado los mismos sitios y alias. Una corrida MCP rápida de 200 sitios frente a un barrido tradicional mayor mide estrategias de cobertura diferentes.
- **Herramientas y fuentes:** en la comparación de planificación, limita al agente a las herramientas del registro que usa el motor interno. Excluye `public_page_reader` y la navegación/búsqueda propia del cliente de esa condición: el lector adicional solo está expuesto por MCP. Evalúa esas capacidades en otra condición de agente con navegación ampliada y registra sus fuentes y lecturas.
- **Presupuestos:** fija antes del ensayo los mismos máximos de consultas, resultados, sitios y alias, además de un límite de tiempo común. Los límites por llamada y el número de rondas no equivalen a un plazo total; el plazo del ensayo debe controlarse aparte. Permite que cada estrategia decida sus pivotes dentro del presupuesto y registra cuánto consume realmente.
- **Tiempo:** mide de inicio a fin, incluyendo planificación, inferencia, llamadas MCP, espera y persistencia. En MCP usa una sesión continua sin intervención humana durante la corrida medida. No compares la suma de duraciones de herramientas con el tiempo total del motor tradicional.
- **Calidad:** usa casos con referencias conocidas y una revisión independiente para contar hallazgos correctos, falsos positivos y relaciones respaldadas por evidencia. Reporta también cobertura y tiempo. Más perfiles o notas no prueban por sí solos una mejor correlación.

Una condición adicional con las mismas entradas, herramientas y pivotes prefijados puede aislar el coste de ejecución del puente MCP. La comparación adaptativa permite que cambien las consultas y los pivotes: esa elección es precisamente parte del aporte que se quiere medir. Los resultados deben admitir mejora, empate o empeoramiento; no se fija un ganador antes de medir.

## Verificación

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
```

La segunda prueba necesita PostgreSQL y permiso para crear esquemas. Crea un esquema temporal, migra un expediente anterior y comprueba HTTP MCP → persistencia → REST web, deduplicación, notas, reanudación, aislamiento de referencias y recuperación. Utiliza herramientas controladas, sin investigaciones reales, y elimina el esquema al terminar.

## SDK

Se utiliza el SDK oficial Python, rama 1.x mantenida (`mcp>=1.20,<2`, versión exacta en `uv.lock`), con FastMCP y Streamable HTTP. Esta elección evita mezclar interfaces incompatibles de las ramas 1.x y 2.x. [Documentación del SDK utilizado](https://py.sdk.modelcontextprotocol.io/v1/).

### Cobertura web por ámbitos

`get_investigation_context` incluye `search_coverage`: presupuesto, consultas usadas y pendientes, resumen por ámbito y hasta veinte propuestas en `next_queries`. Distingue coincidencias verificadas literalmente, consultas sin coincidencias verificadas e indisponibilidad del proveedor. Es una cobertura de consultas del expediente; no representa todos los contenidos de una plataforma.

Revisa `scopes` antes de gastar consultas adicionales. Los ámbitos incluyen perfiles, documentos, foros/comentarios indexados, publicaciones, academia y PDFs abiertos. El agente interno también puede formular `queries` con el contrato validado de MCP. Las anclas literales independientes se exigen todas; las alternativas de nombre se deben expresar como consultas separadas.

`SEARCH_MAX_QUERIES` controla el presupuesto común a los proveedores. Si no se define, se conserva `TAVILY_MAX_QUERIES` por compatibilidad. El respaldo opcional es Tavily → TinyFish → Brave → DuckDuckGo. `BRAVE_API_KEY` habilita Brave; sin clave se omite. Una consulta puede consumir solicitudes en varios proveedores.

El lector público admite HTML, texto y PDFs con texto nativo. Un PDF de imagen, un parser ausente o un límite de extracción dejan un estado explícito. Revisa ese estado antes de interpretar una búsqueda vacía. Consulta la [auditoría OSINT](AUDITORIA_OSINT_2026-10-12.md) para límites, configuración y pruebas.
