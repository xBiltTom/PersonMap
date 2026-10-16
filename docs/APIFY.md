# Apify Social Layer — PersonMap Fair V2

Fase 2 y Fase 2.1, sobre `b7f90f6e892d9b48e05e7c3ebfe5b83f86b845c9`, rama
`feat/footprint-lite-fair-demo`. No es un nuevo pipeline ni un reemplazo de las
fuentes nativas. **Desactivado por defecto; ninguna prueba requiere gasto real.**

## Qué se validó (2026-10-15)

La sección Fase 2.1 al final registra las decisiones vigentes y sustituye el
routing original de Fase 2. No se ejecutaron Actors reales por falta de token.

| Evidencia | Estado | Alcance real |
|---|---|---|
| Búsqueda en Apify Store, README e input schemas de ocho candidatos | **validated** | Consultas de metadatos, no ejecuciones de scrapers |
| Contratos REST de inicio/consulta de runs, datasets y límites | **validated** | Documentación oficial consultada; no prueba de facturación |
| Cuatro normalizadores, router, cliente, límites, errores y persistencia | **fixture-tested** | JSON sintético y transporte HTTP simulado |
| Scraping de cuentas mediante Actors | **not live-tested** | Cero runs reales lanzados por esta entrega |
| Coste, latencia, estabilidad y calidad comparada en vivo | **unknown / not live-tested** | No se presentan estimaciones como mediciones |

La primera búsqueda MCP concurrente tuvo errores de sesión; las búsquedas
secuenciales posteriores y la consulta de esquemas funcionaron. Esto no demuestra
disponibilidad de los scrapers. Una cuenta gratuita de Apify **no** convierte los
Actors en gratuitos. Los precios del Store pueden cambiar según plan y fecha.

## Auditoría y arquitectura

La Fase 1 ya conserva namespaces, consentimiento, seeds declarados, procedencia
automática y listas acumuladas. Se reutilizan registry/dispatch, rondas y vistas
de Frontier, `persist_findings`, trazas, correlación y `durable_runtime`. No hay
migraciones, SDK nuevo, cola paralela ni tablas Apify de evidencias.

```text
Seed/Pivot → motores nativos → observación de perfil/candidato literal
                                  ↓
                         extract_and_apply_pivots
                                  ↓
                        SocialSourceRouter + Frontier
                                  ↓
                    ApifySocialTool (opcional y con consentimiento)
                                  ↓
                    ApifyClient → Actor → dataset acotado
                                  ↓
                    ApifyAdapter → ToolFinding social_account
                                  ↓
                persist_findings / observaciones / correlación
                                  ↓
                        pivotes y siguientes rondas existentes
```

- `app/social/capabilities.py`: specs revisadas y matriz representable en código.
- `app/social/router.py`: decisiones explicables; no ejecuta ni sustituye los
  motores nativos, que siguen despachándose por sus reglas habituales.
- `app/social/apify_client.py`: REST fijo `https://api.apify.com/v2`, transporte
  HTTP compartido, paginación y límites, sin rotación de identidad ni cookies.
- `app/social/apify_adapter.py`: inputs específicos y parsers allowlisted.
- `app/tools/apify_social.py`: BaseTool registrada, reservas, cobertura y fallos.
- `GET /api/v1/sources/social`: matriz/configuración pública segura, sin I/O a
  Apify. El contexto MCP `get_investigation_context` añade `social_sources` con
  routing, presupuesto reservado y diagnósticos. REST detail mantiene el runtime
  en las métricas existentes. No se añade UI ni un endpoint de gasto arbitrario.

## Capability matrix y decisiones

La matriz completa y su estado `enabled` se generan en código. `unknown` indica
que no hay evidencia suficiente; contar seguidores no equivale a extraer sus
perfiles. La columna de capacidades describe el Actor revisado; la integración
puede optar por **no** activar una capacidad que el Actor ofrece.

| Plataforma | Decisión | Actor evaluado | Entradas / salida útil | Lookup / perfil / posts | Comentarios / listas de audiencia | Uso en esta entrega |
|---|---|---|---|---|---|---|
| Instagram | **hybrid** | `apify/instagram-profile-scraper` | username → perfil, bio, enlaces, últimos posts | sí / sí / sí | unknown / unknown | Integrado; declared directo, discovered native-first; sin add-on About |
| TikTok | **hybrid** | `clockworks/tiktok-profile-scraper` | username → authorMeta + vídeos/captions | sí / sí / sí | sí / sí | Integrado; comentarios y audiencia desactivados |
| Threads | **hybrid** | `apify/threads-profile-api-scraper` | username → perfil y posts anidados | sí / sí / sí | unknown / unknown | Integrado; se descarta cualquier perfil privado |
| YouTube | **hybrid** | `streamers/youtube-channel-scraper` | URL canal → canal y vídeos | mediante URL / sí / sí | no / no | Integrado; sin shorts, streams, descargas o CAPTCHA de correo |
| Reddit | **native**; Apify diferido | `apify/reddit-scraper` | username/URL → perfil, posts, comentarios en modos separados | sí / sí / sí | sí / unknown | Prioridad alta; contrato oficial reevaluado; sin token para validar utilidad/coste real |
| X/Twitter | **native**; Apify diferido | `apidojo/twitter-profile-scraper` | username/URL → autor, tweets y replies | sí / sí / sí | replies sí / unknown | No integrado; consulta base facturable, calidad/latencia sin medir |
| Facebook personal | **native**; este Actor **not worth using** | `apify/facebook-posts-scraper` | URL de Page pública → posts de Page | no / no para persona / sí Page | no en el contrato revisado / no | El input schema dice Pages públicas, no perfiles personales, aunque el resumen comercial es más amplio |
| LinkedIn | **native**; Apify diferido | `harvestapi/linkedin-profile-scraper` | URL/public identifier → detalle profesional | sí / sí / no | no / unknown | No integrado; evaluar procedencia pública; el modo email/SMTP queda excluido |
| Telegram | **native** | ninguno seleccionado | verificador público especializado existente | existente | no nuevo | No justifica duplicar el motor propio |
| GitHub | **native**; duplicado Apify **not worth using** | ninguno seleccionado | scanner de perfil/repos/commits con roles de evidencia | existente | no nuevo | Mantener el especialista, no sustituirlo por un perfil genérico |
| Gravatar | **native** | ninguno seleccionado | asociación exacta por email y enlaces públicos | existente | no nuevo | Conservar |
| Google | **native** | ninguno seleccionado | GHunt + búsquedas públicas complementarias | existente | no nuevo | Conservar sesión del operador y alcance actual |
| Academia | **native** | ninguno seleccionado | OpenAlex/Crossref, nombre/ORCID/DOI y autoría contrastada | existente | no nuevo | No reemplazar; ORCID sigue descubrible |
| Email, brechas, teléfono, documentos y búsqueda | **native**; duplicación Apify **not worth using** | ninguno seleccionado | herramientas actuales / SearchDorker | existente | no nuevo | Sin cambios en filtros, técnicas o precisión |

No hay política `apify` exclusiva seleccionada: no existe evidencia comparativa
suficiente para quitar una fuente nativa. Las cuentas declaradas con plataforma
son elegibles inmediatamente; los descubrimientos requieren observación nativa y Frontier.
Maigret/WhatsMyName permanecen activos también para usernames etiquetados.

### Precios anunciados, NO mediciones

Snapshot del Store para FREE tier, consultado el 15-10-2026:

| Actor | Componentes anunciados en el Store |
|---|---|
| Instagram profile | USD 0.0026 por perfil; About USD 0.007 adicional, no activado |
| TikTok profile | USD 0.003 por resultado; múltiples add-ons separados, no activados |
| Threads profile | USD 0.005 por perfil |
| YouTube channel | USD 0.0013 por vídeo |
| Reddit oficial (Fase 2.1) | FREE: USD 2/1000 users, 4/1000 posts, 3.20/1000 comentarios, USD 0.001/inicio; no medidos |
| Twitter profile | USD 0.016 por consulta de perfil, incluye primeros 40 tweets según el Store; extras separados |
| Facebook posts | USD 0.005 por post y USD 0.001 por inicio; filtros opcionales adicionales |
| LinkedIn profile | USD 0.004 por detalle de perfil; modo email adicional no seleccionado |

No se calcula un precio final con estos componentes. Mínimos, eventos, uso de
plataforma, planes y cambios del Actor pueden afectar el cobro. Por ello las
clases estimadas de coste/latencia del código permanecen **unknown**, no “barato”
o “rápido” sin medición. Alternativas del Store examinadas en discovery incluyen
`data-slayer/instagram-posts`, `apidojo/tiktok-profile-scraper`,
`louisdeconinck/reddit-user-info-scraper`, `epctex/twitter-profile-scraper`,
`scraper_one/facebook-posts-search` y `thenetaji/threads-scraper`: no se integran
sin revisar completamente sus contratos. No se prefirió una etiqueta FREE a la
evidencia de uso/calidad. El Actor de YouTube de email/CAPTCHA encontrado en la
búsqueda se excluye del alcance (no se usa ni se prueba).

## Routing y namespaces

1. `foo / instagram` declarado por el sujeto permite Apify inmediato para esa
   cuenta, con consentimiento/configuración/presupuesto. La existencia y el contenido
   se observan automáticamente. El barrido nativo continúa siendo elegible. Un
   namespace desconocido va a fuentes nativas; no se inventa un Actor.
2. Sin namespace: Maigret/WhatsMyName y búsqueda/verificación nativas descubren
   plataformas primero. No se multiplican runs por cada plataforma posible.
3. Para cuentas descubiertas automáticamente, son entradas plausibles: un perfil `verified` de SocialVerifier; un resultado
   Claimed de Maigret o WhatsMyName con control negativo pasado; o una URL exacta
   de perfil encontrada por SearchDorker con `literal_match=true`. Un snippet no
   prueba existencia: se conserva como candidato, no como identidad.
4. Una URL fabricada, una sugerencia del agente, un control negativo sin probar,
   una mención no literal o el propio output de Apify NO satisfacen por sí solos
   el gate de descubrimientos. Se respetan las URLs admitidas por la vista de
   ejecución de Frontier para descubrimientos; los seeds de cuenta explícitos no
   requieren esa admisión.
5. El router exige opt-in del operador, token, plataforma habilitada y
   consentimiento general del sujeto; en otro caso la decisión es native.
   `hybrid` describe una fuente elegible, no una orden de volver a ejecutarla:
   BaseTool aplica después cobertura/run keys y presupuesto. La decisión final
   de despacho está en `tool_readiness.can_run`; el contexto muestra ambos niveles.
6. `apify_social` convierte exclusivamente el perfil/canal pedido. Si el Actor
   devuelve otro handle/ID, privado, restricción de edad o error, se descarta.
   Una URL o URL + handle consultado sin atributos públicos observados tampoco
   crea una cuenta: no se trata el eco de una consulta como existencia comprobada.
   Un canal YouTube por ID exige coincidencia exacta sensible a mayúsculas; un
   cambio handle → ID necesita el handle estructurado observado, no solo un eco
   de la consulta. Los aliases de un mismo canal se registran para evitar ciclos.

`social_native_profiles` conserva observaciones nativas acotadas. Su fusión es
monótona para que enriquecer una entidad no borre la evidencia previa. No es otro
almacén de identidades. El router **recomienda** fuentes nativas; los motores
existentes las ejecutan como antes, sin una nueva orquestación Lite.

## Normalización, procedencia y pivotes

Cada cuenta sigue siendo `ToolFinding(entity_type="social_account")`. Bio, nombre,
website, avatar público seguro y `public_content` acotado van a `metadata_info`.
Los posts normalizados conservan URL, ID, texto/caption/título, fecha, hashtags y
menciones estructuradas. No se crean entidades de inferencias o de Exposure Lens.
No se retienen filas crudas, comentarios de terceros, followers/following,
coautores, sugerencias de related profiles ni descargas de medios.

`metadata_info.collection_sources[]` conserva, cuando el proveedor lo devuelve:

```text
provider=apify, actor (owner/name), actor_id, run_id, dataset_id,
build_id, build_number, source_platform, source_url, retrieved_at,
query (platform/username/profile_url), input allowlisted, usage numérico opcional
```

Las listas de fuentes se fusionan por el deduplicador común; se corrigió su
idempotencia para no perder `source_tools` previamente agregado al deduplicar
otra vez. No se cambia la política de correlación. `verification_status=verified`
significa que se observó el recurso público pedido, **no** identidad verificada
ni el badge del proveedor. `ownership_status=subject_declared` para cuentas
exactas declaradas, `unverified` para otras; la persistencia común
asigna siempre `origin=automatic/status=discovered` a la nueva observación.
Ningún Actor puede escribir una decisión humana `confirmed`.

Pivotes: enlaces externos/website estructurados → candidatos URL; el handle
observado → candidato de alias; un `mailto:` explícito y válido en un campo de
enlaces públicos → candidato email. No se minan emails de captions/bios libres,
ni se convierten mentions, comentarios, perfiles sugeridos o coautores en aliases
del objetivo. Las reglas de formato/ruido y Frontier siguen aplicándose.

Claves canónicas por plataforma/recurso/identificador, historial por Actor y
reservas persistidas evitan `perfil → website → perfil` y reconsultas por
mayúsculas, alias de host o continuaciones del workspace. `force` no limpia el
presupuesto ni vuelve a cobrar un perfil explorado; se requiere una nueva
investigación explícita para repetirlo en esta versión.
Una consulta idéntica sin `force` reutiliza su ejecución persistida cuando está
disponible: su fingerprint depende de inputs admitidos/configuración, no de la
lista mutable de pendientes. Si no hay ejecución reutilizable ni presupuesto,
la llamada se rechaza sin iniciar un Actor.

## Configuración

Configurar en el entorno **del backend** (localmente `backend/.env`; Compose
recibe `.env` raíz). Nunca usar `NEXT_PUBLIC_*` para el token. Compose ya no
inyecta el `.env` completo en el contenedor frontend; solo sus valores públicos.

```dotenv
APIFY_ENABLED=false
APIFY_TOKEN=
APIFY_PLATFORMS=["instagram","tiktok"]
APIFY_ACTOR_BUILDS={}
APIFY_MAX_ACTORS=2
APIFY_MAX_RUNS=2
APIFY_MAX_PROFILES_PER_ACTOR=3
APIFY_MAX_CONTENT_ITEMS_PER_PROFILE=10
APIFY_DATASET_PAGE_SIZE=5
APIFY_RUN_TIMEOUT=60
APIFY_BATCH_TIMEOUT=150
APIFY_REQUEST_TIMEOUT=15
APIFY_MAX_RETRIES=1
APIFY_PARALLELISM=1
APIFY_MAX_CHARGE_PER_RUN_USD=0.05
APIFY_MAX_CHARGE_PER_INVESTIGATION_USD=0.10
APIFY_MAX_RESPONSE_BYTES=2000000
```

`APIFY_ENABLED=true` y un token no bastan: la investigación necesita
`subject_consent=true` de la Fase 1. No se infiere del permiso de infostealers ni
de argumentos LLM/MCP. Los expedientes V1 sin consentimiento general guardado no
se envían a Apify. Sus fuentes nativas y su compatibilidad siguen funcionando.

`APIFY_PLATFORMS` solo habilita adapters implementados; Threads/YouTube se añaden
explícitamente si se desea. `APIFY_ACTOR_BUILDS` permite fijar por plataforma un
tag/build validado por el operador. Vacío usa `latest`; se conserva el build real
devuelto para trazabilidad, pero no se promete estabilidad de ese tag móvil.
No se permiten Actor IDs, scripts JS, sesiones, proxies, cookies, destinos de red
o parámetros arbitrarios desde una investigación o el frontend.

## Presupuesto, errores y límites

- Reservas síncronas antes del primer await, acumuladas por investigación en
  `apify_runtime.runs`: máximo de runs, Actors distintos, perfiles por Actor y USD
  **reservados**, no supuestas facturas. No se devuelven reservas de starts
  ambiguos o trabajos cancelados: la prudencia es gastar menos, no reintentar.
- Cada POST lleva `timeout`, `maxItems`, `maxTotalChargeUsd`, build y
  `restartOnError=false`. `maxItems` de Apify solo limita ítems cobrables de
  pay-per-result, **no garantiza** filas producidas. También se acotan inputs
  específicos (TikTok/YouTube: contenido por perfil), lectura paginada y contenido retenido localmente.
  Instagram/Threads producen un perfil por input; sus posts anidados no tienen
  límite remoto documentado y se recortan localmente: como máximo ese número de
  contenidos **por perfil**, no una promesa de límite de posts remotos por Actor.
  Filas leídas: perfiles del batch para Instagram/Threads; perfiles × contenido
  por perfil para TikTok/YouTube. Un batch cuenta como un run y reserva todos sus perfiles.
- `maxTotalChargeUsd` es un guardarraíl solicitado al proveedor, no un precio
  medido ni garantía contable independiente. Costes reportados y compute units
  se guardan si son numéricos; los totales pueden ser eventualmente consistentes.
- `APIFY_MAX_RETRIES` solo reintenta GET por red/5xx. Starts de pago nunca se
  reintentan, ni siquiera ante 5xx: un timeout podría ocultar un run ya iniciado.
- Timeout local/cancelación solicita abort del run conocido (hasta 5 s extra
  para limpieza). `abort_requested` no afirma que el proveedor lo haya detenido
  ya. Sin run ID tras un POST ambiguo se conserva `start_uncertain`, no se repite;
  el timeout y límite de cargo remotos siguen siendo necesarios.
- Paralelismo compartido por proceso/event loop; límite adicional HTTP global y
  por host existente. No es un presupuesto distribuido multi-worker.
- 401/403/402/429 deshabilitan Apify para ese expediente; red/5xx, formato cambiado,
  dataset vacío o filas inutilizables quedan como fallos/huecos, no `not_found`.
  Filas útiles de runs fallidos y resultados ya completados de otros jobs se
  conservan. La caída de esta fuente no cancela otras fuentes nativas.
- Runtime se guarda al cierre del motor/tool usando los commits existentes.
  Las reservas Apify se recuperan también con Frontier desactivada; su flag no
  reinicia ni oculta el presupuesto de la familia de fuentes pagadas.
  **No hay ledger transaccional pre-POST resistente a caída dura del proceso**:
  un crash entre inicio remoto y commit puede perder una reserva. Revisar Console
  antes de continuar ese expediente; no se promete exactly-once. Una siguiente
  fase puede conectar checkpoints/ledger sin rediseñar cliente o adapters.
- Borrar un expediente en PersonMap no borra automáticamente runs/datasets de
  Apify. El operador debe revisar permisos, retención y límites de gasto en
  Console; esta entrega no implementa limpieza remota ni garantiza retención.
- Respuestas limitadas también en bytes descomprimidos. Se descartan campos
  no allowlisted, headers y respuestas de error crudas. URLs con credenciales,
  destinos privados o query strings (salvo IDs públicos watch/profile) se
  rechazan: incluye URLs CDN firmadas que por ello pueden no mostrar avatar.
  Parámetros de tracking conocidos (`utm_*`, `ref`, `fbclid`) se eliminan sin
  perder el enlace público; no se eliminan firmas para intentar acceder al recurso.
  Se redactan el token configurado y patrones Bearer/Apify en texto retenido.
- No login de sujetos, cookies, acceso a privados, bypass de autenticación,
  CAPTCHA de correos, extracción de audiencias o análisis semántico.

## Añadir un Actor

1. Buscar en el Store; leer README, esquema completo y output, condiciones de
   acceso público, límites, precios y métricas de uso. No basta el texto comercial.
2. Añadir spec/capacidades y decisión explícita en la matriz. Mantener desactivado
   si no hay un caso mejor que las fuentes nativas o si necesita acceso privado.
3. Escribir builder allowlisted con límites remotos y sin extras/cookies/IA;
   normalizador de identidad del recurso, privacidad, fuentes y contenido acotado.
4. Añadir fixtures rotulados sintéticos y tests de errores, budgets, run keys,
   dedupe, consentimiento, fuga de secretos y no atribución de identidad.
5. No promover terceros mencionados/sugeridos a identificadores del sujeto.
6. Medir dentro de la autorización del operador una cuenta pública apropiada, lote mínimo y
   cargo acotado; registrar run/build/dataset, duración, `usageTotalUsd` tras su
   consolidación, campos útiles y falsos positivos frente a las fuentes nativas.
   Esas métricas faltan hoy: no sustituir `unknown` por cifras inferidas.
7. Fijar build cuando proceda y habilitar la plataforma por configuración; nunca
   eliminar una fuente nativa solo porque el Actor exista.

## Pruebas reproducibles

```bash
cd backend
.venv/bin/python -m pytest tests/test_apify_social.py tests/test_footprint_foundation.py tests/test_persistence.py tests/test_correlation_evidence.py tests/test_pivot_frontier.py tests/test_workspace_updates.py tests/test_agent_fallback.py tests/test_hybrid_engine.py -q
.venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
.venv/bin/python -m pytest -q --durations=10
.venv/bin/python -m pytest -q --ignore=tests/test_scan_progress.py --durations=5
```

La integración PostgreSQL usa esquemas temporales, no expedientes reales. El
caso Apify simula HTTP y comprueba una entidad compartida nativa/Actor, trazas,
fuentes, pivotes, recarga sin caché y `force` sin nuevo gasto. Las fixtures
`tests/fixtures/apify_social.json` son sintéticas, **no** un dataset de producción.

Resultados de cierre registrados (15-10-2026):

- **205 pruebas** en el conjunto Apify/Foundation/persistencia/correlación/
  Frontier/workspace/motores; incluye **73 casos Apify nuevos**.
- **17 pruebas PostgreSQL/REST/MCP** aprobadas, incluida persistencia Apify real
  en PostgreSQL con HTTP externo simulado.
- **205 regresiones de fuentes nativas** aprobadas (búsqueda, academia, GHunt,
  teléfono, GitHub e infostealers), más **63 de Maigret/WhatsMyName**.
- Frontend sin rediseño: **2 pruebas de entrada + 4 del grafo**, TypeScript sin
  errores. Aviso Node preexistente `MODULE_TYPELESS_PACKAGE_JSON`, no un fallo.
- YAML Compose validado; frontend solo recibe `NEXT_PUBLIC_API_URL` y `PORT`;
  el backend conserva su `env_file`. `git diff --check` sin errores.
- La corrida integral aprobó **1002 pruebas, 19 excluidas** por marcadores
  (751,44 s). Después se añadieron tres casos de rechazo de ecos de consulta y
  la regresión general aprobó **1000 pruebas, 19 excluidas** (201,84 s), omitiendo
  únicamente los cinco casos lentos de `test_scan_progress.py`, ya aprobados en
  la corrida integral; no se modificaron ese archivo ni el motor de escaneo.
  El ajuste posterior de reutilización de ejecuciones se validó con los **205**
  casos específicos y las **17** pruebas PostgreSQL/REST/MCP sobre el código final.

La validación detectó y corrigió dos problemas: tuplas en la matriz no conservaban
igualdad tras JSONB (se exponen listas JSON), y una segunda deduplicación podía
perder `source_tools` ya agregado (se conserva idempotentemente). No se cambian
los pesos de correlación para resolverlos. También se bloquean resultados que
solo repiten URL/username consultados sin atributos observados y se preservan
fingerprints estables para reutilizar ejecuciones sin pagar de nuevo.

## Referencias consultadas

- Store/README/input/output de los ocho Actors enlazables en
  `https://apify.com/<owner>/<actor>` según la matriz.
- [Run Actor](https://docs.apify.com/api/v2/actors-runs-post).
- [Get run](https://docs.apify.com/api/v2/actor-run-get).
- [Actor runs / abort](https://docs.apify.com/api/v2/actor-runs).
- [API y flujo de datasets](https://docs.apify.com/api/v2).

## Preparación para Fase 3 (sin implementarla)

La futura Lite puede consultar matriz/router, ordenar fuentes nativas rápidas y
llamar a la misma BaseTool solo para candidatos admitidos, reutilizando reservas,
normalizadores y pivotes. Aún no hay preset Lite nuevo, deadline global de 3–4
minutos, Verification Gate, Exposure Lens, reconstrucción IA, Graph V2 ni UI de
feria. No se usa texto público para producir inferencias sobre el sujeto.

La Fase 2.1 reemplaza la reserva de filas por Actor con presupuestos separados de
perfiles y contenido. La Fase 3 podrá reservar margen por oleada sin cambiar transporte.

## Fase 2.1 — Fair Routing & Live Validation

Base: `b20b045c08c142646e1ea800e0a04d28732a0c74`, misma rama; Fases 1 y 3 intactas.
Se conserva `SocialSourceRouter → ApifySocialTool → ApifyClient → ApifyAdapter → ToolFinding`.

### Routing y ownership

- Cuenta declarada con plataforma soportada: Apify elegible inmediatamente; no
  espera observación nativa ni admisión de Frontier. Las herramientas nativas
  permanecen elegibles para descubrir otras plataformas. El router no añade una
  orquestación nueva ni promete ejecución simultánea del scheduler existente.
- Alias declarado sin plataforma: discovery nativo, observación plausible,
  admisión de Frontier y entonces enriquecimiento. Cero fan-out pagado.
- Candidato automático o pivot: el mismo gate nativo y Frontier; una coincidencia
  del alias en otra plataforma no transfiere ownership.
- Continúan consentimiento general, enabled/token, allowlist y todos los límites.

`metadata_info.ownership={status: subject_declared, needs_review: false, seed_id,
seed: {kind,value,platform}}` representa la asociación cuenta-persona.
`seed_id` es SHA-256 del seed serializado de forma estable, sin migrar Foundation.
`ownership_status` y `ownership_review_required` exponen el mismo contrato.
La persistencia recalcula estos campos desde los seeds del target guardado,
incluso para observaciones nativas; no acepta decisiones de ownership del tool/LLM.
Las cuentas que no coincidan conservan `unverified` y revisión requerida.

`provenance` del perfil continúa `automatic/discovered`; cada contenido guarda
`origin=automatic` y `collection_source` con actor/run/dataset/build, plataforma,
query individual, input del batch, timestamp y URL pública. Declarar una cuenta
no declara la bio ni los posts. El futuro Gate debe consultar
`ownership_review_required` para cuentas y `provenance.needs_review` para otros
hallazgos; el segundo sigue describiendo la observación, no la atribución de la cuenta.
No se implementa Gate UI ni se marca como confirmed contenido o pivotes.

### Batching y límites

Los cuatro contratos admiten arrays: Instagram/Threads `usernames`, TikTok
`profiles`, YouTube `startUrls`. Se agrupan entradas pendientes por plataforma/Actor;
el build configurado es único por plataforma y queda en la reserva/run key.
Un batch reserva un run, el cargo completo por run y todos sus perfiles antes
del primer await. Dedupe y cobertura usan claves individuales, incluso tras reload
sin caché o force. Cada request normaliza solamente filas cuyo handle/ID observado
coincide; no atribuye por orden de llegada. Un perfil fallido o un parser que falla
para él no descarta los restantes; runtime incluye outcomes por perfil.

- `APIFY_MAX_PROFILES_PER_ACTOR=3`: cuota acumulada por Actor e investigación,
  incluyendo intentos fallidos y reservas antiguas (compatibilidad Fase 2).
- `APIFY_MAX_CONTENT_ITEMS_PER_PROFILE=10`: contenido retenido por perfil;
  también límite remoto por perfil TikTok/YouTube. Instagram/Threads solo permiten
  recortar localmente sus posts anidados; no se promete limitar ese trabajo remoto.
- `APIFY_MAX_ITEMS_PER_ACTOR` queda aceptado como configuración obsoleta; ya no
  gobierna gasto ni contenido. Migrar al par anterior. No es un tercer límite activo.
- Defaults restantes: 2 Actors, 2 runs, USD 0.05/run y USD 0.10 reservados/investigación,
  timeout 60 s/run, 150 s/lote, paralelismo 1. No son costes medidos.
- Lectura/maxItems: N filas en Actors de perfil; N × contenidos en Actors de vídeo.
  Nunca se interpreta una fila de perfil como una sola publicación.

### Catálogo final y reevaluación

| Plataforma | Actor | Estado Fase 2.1 |
|---|---|---|
| Instagram | `apify/instagram-profile-scraper` | Integrado, batches; allowlist por defecto |
| TikTok | `clockworks/tiktok-profile-scraper` | Integrado, batches; allowlist por defecto |
| Threads | `apify/threads-profile-api-scraper` | Integrado, batches; opt-in en allowlist |
| YouTube | `streamers/youtube-channel-scraper` | Integrado, batches; opt-in en allowlist |
| Reddit | `apify/reddit-scraper` | Alta prioridad; native/deferred hasta prueba real |
| X | `apidojo/twitter-profile-scraper` | Native/deferred hasta prueba real |
| LinkedIn | `harvestapi/linkedin-profile-scraper` | Native/deferred; falta validar detalle público/coste |
| Facebook | `apify/facebook-posts-scraper` | Native; contrato de Pages no cubre perfil personal |

Todos requieren además `APIFY_ENABLED=true`; default global sigue false.

[Reddit oficial](https://apify.com/apify/reddit-scraper) y su
[input schema](https://apify.com/apify/reddit-scraper/input-schema) se revisaron
el 15-10-2026. Admite usernames, modos users/posts/comments y límites
`maxPostsPerUser`/`maxCommentsPerUser`. El perfil devuelve karma/fecha/flags;
posts y comentarios son registros separados con autor. Aporta capacidades que
justifican prioridad alta para Exposure Lens, pero sin token no se puede demostrar
funcionamiento ni mejora suficiente frente al stack nativo. No se habilita por
una promesa del Store. El benchmark incluye los tres modos sin integrarlo en producción.
El [pricing oficial](https://apify.com/apify/reddit-scraper/pricing) anuncia para
FREE USD 0.002/user, 0.004/post, 0.0032/comentario y 0.001/inicio; son tarifas,
no costes observados. No se aplican las conclusiones del anterior Actor comunitario.

[X input](https://apify.com/apidojo/twitter-profile-scraper/input-schema) admite
`twitterHandles[]`/`startUrls[]`, `maxItems` global, replies y About opcionales.
El probe deshabilita ambos extras y retweets. Su
[pricing](https://apify.com/apidojo/twitter-profile-scraper/pricing) anuncia
USD 0.016/query de perfil, USD 0.0004/item, queries adicionales de replies/About;
README anuncia primeros 40 tweets incluidos. No se infiere factura ni fiabilidad.
Faltan latencia, estabilidad y utilidad real: permanece fuera de ACTORS, incluso
si se añade twitter a la allowlist. Lo mismo aplica a Reddit.

Contratos de batch consultados:
[Instagram](https://apify.com/apify/instagram-profile-scraper/input-schema),
[TikTok](https://apify.com/clockworks/tiktok-profile-scraper/input-schema),
[Threads](https://apify.com/apify/threads-profile-api-scraper/input-schema),
[YouTube](https://apify.com/streamers/youtube-channel-scraper/input-schema).

### Live validation y builds

El backend no dispone de `APIFY_TOKEN`: **0 runs reales**. Todos los Actors:
`not_live_validated`; coste, latencia y build validado **null / no medidos**.
Informe versionado: [apify-phase21-validation-2026-10-15.json](audits/apify-phase21-validation-2026-10-15.json).
No se fija un build inventado ni se usan las métricas sintéticas de tests como reales.

Comando sin token, sin red ni gasto (usar ruta de informe nueva):

```bash
cd backend
.venv/bin/python scripts/apify_live_benchmark.py --output /tmp/apify-preflight.json
```

Con token backend, cuentas públicas apropiadas y autorización ya otorgada para
este benchmark, ejecutar una sola vez (reemplazar handles de ejemplo):

```bash
.venv/bin/python scripts/apify_live_benchmark.py \
  --account instagram:PUBLIC_TEST_HANDLE --account tiktok:PUBLIC_TEST_HANDLE \
  --account threads:PUBLIC_TEST_HANDLE --account youtube:PUBLIC_TEST_HANDLE \
  --content-limit 1 --charge-per-run 0.03 --charge-total 0.12 \
  --output /tmp/apify-four-platforms.json
```

Reddit/X por separado, solo si se desea evaluar su promoción posterior:

```bash
.venv/bin/python scripts/apify_live_benchmark.py \
  --account reddit:PUBLIC_TEST_HANDLE --reddit-mode users \
  --output /tmp/apify-reddit-users.json
# Para actividad: otro informe con --reddit-mode posts o comments, manteniendo los límites.
.venv/bin/python scripts/apify_live_benchmark.py \
  --account twitter:PUBLIC_TEST_HANDLE --output /tmp/apify-x.json
```

El script acepta máximo 2 perfiles/plataforma, 6 runs y USD 0.05/run, USD 0.20
por invocación como techos absolutos; defaults USD 0.03/run y USD 0.12 total.
Comprueba la suma de reservas previstas contra el límite antes de comenzar;
checkpoint por run antes del POST, sin retry de starts ambiguos. Rechaza sobrescribir
un informe existente: revisar ese informe antes de cualquier nueva ejecución.
Los límites de benchmark son independientes del presupuesto de una investigación.
Varias invocaciones con informes distintos no comparten ledger monetario.

Registra status, build solicitado/real, tiempo total local, usageTotalUsd si existe,
perfiles solicitados/normalizados, contenidos útiles, errores y claves del schema
(incluyendo claves de authorMeta/aboutChannelInfo), sin guardar filas crudas.
Reddit/X se etiquetan probe-only: conteos útiles pendientes de revisión, no se
consideran adapters ni builds validados. En los cuatro integrados, éxito con
todos los perfiles observados produce `APIFY_ACTOR_BUILDS={platform: buildNumber}`;
la validación de contenido se registra aparte y puede ser `not_observed`.
Copiar ese mapa a configuración tras revisar el informe y conservar run/build ID,
fecha, coste y latencia. `latest` sigue solo como fallback sin garantía de feria.
Los cargos reportados pueden requerir consolidación posterior en Apify Console.

### Riesgos pendientes para Fase 3

Validación real y pin de builds pendientes; cobertura de contenido Threads/Instagram
puede variar; filas planas vacías no prueban inexistencia del perfil. Reddit/X
necesitan medición y parsers contra outputs reales antes de habilitarse.
El ledger de investigación sigue sin checkpoint transaccional pre-POST resistente
a caída dura y sin coordinación distribuida multi-worker. Configurar cuotas
pequeñas; un batch nunca amplía esas cuotas. La orquestación nativa/Apify sigue
la planificación existente, sin SLA global nuevo. No se cambian especialistas,
presets, UI, correlación, grafo ni se inicia Fase 3.

### Pruebas de cierre de Fase 2.1

- `tests/test_apify_social.py tests/test_apify_benchmark.py -q`: **91 aprobadas**
  (80 integración Apify, 11 benchmark). Incluye routing declarado inmediato,
  native-first automático, ownership/revisión, batches, fallos parciales,
  provenance individual y conservación de reservas antiguas.
- `tests/test_mcp_workspace_db.py -m db -q -x --tb=short`: **18 aprobadas**
  (31.16 s); PostgreSQL real con HTTP Apify simulado. Parametriza con/sin observación
  nativa previa y demuestra ejecución directa, persistencia y no gasto repetido.
- `pytest -q --ignore=tests/test_scan_progress.py --durations=5`: **1017 aprobadas,
  19 excluidas por marcadores**, 165.08 s. No incluye los cinco tests lentos de
  progreso, que no se modifican. La prueba adicional de compatibilidad de reservas
  antiguas se añadió después de la colección general y pasó en el conjunto de 91.
- La primera corrida restringida de regresión y PostgreSQL se interrumpió por
  bloqueo de I/O; las corridas anteriores aprobadas se ejecutaron fuera del sandbox.
- `git diff --check`: sin errores. Preflight del benchmark: token_missing,
  cero starts pagados; informe versionado. Ninguna cifra de fixtures es una medición real.
