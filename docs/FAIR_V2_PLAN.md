# PersonMap Fair V2 — contrato de evolución

Rama: `feat/footprint-lite-fair-demo`. Entregas cerradas: **Fase 1 y Fase 2**.
Base auditada: `main` en `e5a199ba34df0cdb100322f3e2cf7969e82268ed` (sin modificar).
Los datos iniciales son propios o cuentan con autorización explícita. Descubrir
un identificador, verificar que existe un perfil y atribuirlo a una persona son
tres operaciones diferentes. Ningún peso de correlación es una probabilidad.

## Auditoría de la arquitectura existente

- `models/target.py` conserva campos escalares y `extra_data` JSONB mutable;
  `Investigation` enlaza target, entidades, observaciones, ejecuciones, relaciones,
  sesiones y notas. El JSON permite ampliar sin migración destructiva.
- `tools/base.py:TargetContext` acumula pivotes; sus métodos `all_*` son la vía
  habitual de consumo. `rule_engine` ejecuta rondas; `hybrid_engine` reutiliza el
  barrido y el dispatch del agente. REST y MCP comparten `WorkspaceService`.
- `pivot_rules` valida/excluye ruido; `PivotFrontier` conserva evidencias,
  admite seeds P0 y prioriza exploración, no identidad. Sus vistas de ejecución
  y presupuestos deben conservar todos los seeds iniciales.
- `identity/evidence.py`, resolver y proyección relacionan observaciones por
  roles de evidencia. Alias solo: atracción cero; ownership sigue `unverified`.
  El grafo REST/GraphML usa esa proyección, sin reescribir expedientes antiguos.
- `persistence.py` centraliza deduplicación y preserva observaciones por fuente,
  URLs y capas. Es el punto compartido para marcar descubrimientos automáticos.
- SearchDorker ya consume listas, valida coincidencias literales y coordina
  Tavily/TinyFish/DDG con cobertura y límites. No se modifican sus filtros.
- GHunt usa biblioteca/entorno aislados, selección de consultas, sesión del
  operador y presupuestos. PeoplePa/GAIA no confirman propiedad; colaboradores
  de Drive no se convierten en identificadores del sujeto.
- AcademicFinder conserva OpenAlex/Crossref, nombre/ORCID/DOI, controles de
  autoría y procedencia. ORCID continúa descubriéndose desde resultados.
- UsernameFinder/Maigret y WhatsMyName mantienen workers, controles negativos,
  catálogo, extracción tipada y límites. Una plataforma declarada es contexto,
  no filtro global ni prueba de pertenencia de cuentas encontradas.
- BreachChecker, Gravatar, GitHub y correo usan `all_emails/all_usernames`;
  PhoneLookup emplea `phone_identity` (PE por defecto, E.164 y extensiones).
  SocialVerifier mantiene su score operacional de existencia; la correlación
  final ya es independiente de ese score.
- El frontend Next/React comparte contratos en `lib/types.ts`, formulario,
  historial, página de investigación, SSE, hallazgos, mapa e inspector. Se cambia
  solo la captura de datos y su contrato, no el workstation ni su mapa.

Documentación revisada: `CORRELACION.md`, `PIVOT_FRONTIER.md`, `OSINT_SOURCES.md`,
`GHUNT.md`, `MAIGRET.md`, `MOTOR_BUSQUEDA.md`, `ACADEMICO.md` y guía instalada
de Next para componentes cliente. Este documento prevalece sobre las antiguas
descripciones del formulario con DNI/ORCID/contexto académico.

## Fase 1 — Foundation V2 (implementada)

### Contrato de entrada

```json
{
  "target": {
    "input_version": 2,
    "given_names": "Ana María",
    "family_names": "Pérez Díaz",
    "emails": ["ana@gmail.com", "ana@universidad.edu.pe"],
    "usernames": [
      {"username": "ana-code", "platform": "github"},
      {"username": "ana123", "platform": null}
    ],
    "phones": ["+51912345678", "+14155552671"]
  },
  "subject_consent": true,
  "self_consent": false,
  "strategy": "rule_based"
}
```

- `given_names` y `family_names` separados; conservan tildes y reducen espacios.
  Al menos un identificador, no todos los campos, es obligatorio.
- Hasta 30 entradas de cada clase; listas vacías válidas. Emails completos en
  minúsculas, sin eliminar puntos ni etiquetas `+`. Teléfonos usan exactamente
  `phone_identity`: E.164 + `;ext=`, PE predeterminado; inválidos se rechazan.
- Alias: trim, quitar `@` inicial; conservar Unicode y mayúsculas porque hay
  plataformas sensibles a ellas. Deduplicar por `(username, platform)`; conservar
  mismo alias en plataformas diferentes o sin etiqueta. `all_usernames` ofrece
  valores únicos a los motores; el namespace permanece en los seeds.
- Plataforma libre opcional, trim/minúsculas; no enumeración cerrada. Un datalist
  sugiere plataformas conocidas sin impedir otras.
- La captura principal NO pide carrera, intereses, profesión, ubicación, ORCID,
  descripción, DNI, institución ni URLs. API V2 rechaza los campos históricos
  incompatibles y combinaciones de escalares que contradicen sus listas.
- Consentimiento general obligatorio en V2, validado en backend (REST y MCP).
  `self_consent` sigue separado, opcional y cerrado por defecto para infostealers:
  consentir la auditoría NO habilita automáticamente esa fuente.

### Persistencia y compatibilidad

`Target.extra_data.footprint_input` guarda el contrato normalizado versión 2 y
`declared_seeds`. `extra_data.subject_consent` guarda el consentimiento general;
`self_consent` mantiene su significado anterior. Procedencia y consentimiento
reservados se generan en servidor, no se aceptan mediante `extra_data` del cliente.
`TargetRead.footprint_input` expone el objeto tipado además del JSON histórico.

Los escalares `full_name/email/username/phone` son espejos (nombre compuesto y
primera entrada). Se conservan columnas/campos históricos, clientes V1 y MCP;
una entrada con campos V2 exige consentimiento aunque omita `input_version`.
V1 sigue su política de consentimiento previa: esto es compatibilidad explícita,
no una nueva garantía retroactiva para expedientes históricos. No hay migración,
relleno de BD ni reinterpretación de datos antiguos como declarados por el sujeto.
La lectura API tolera `extra_data`/`metrics` NULL de filas históricas como objetos
vacíos, sin actualizar sus columnas; la integración detectó ese caso al validar
un expediente creado antes de las migraciones actuales.

`TargetContext.from_target` hidrata `declared_seeds` **sin** insertarlos en
`discovered_*`. Los `all_*` combinan escalares + declarados + descubiertos,
deduplicados; build_call_context, reglas e híbrido conservan los seeds. Argumentos
del agente no generan declaraciones del sujeto. Frontier admite todos como P0
manteniendo namespace en el contrato, no duplicando búsquedas por plataforma.
La correlación compara contra TODOS los datos iniciales, nunca los descubiertos,
con los mismos roles y pesos anteriores. El mapa añade metadata de seeds, no
nuevos tipos de nodos ni un rediseño.

### Procedencia de dominio

`schemas/footprint.py` define `DataProvenance`:

| Origen | Estado | Afirmado por sujeto | Revisión pendiente |
|---|---|---|---|
| subject | declared | true | no |
| automatic | discovered | false | sí |
| automatic | confirmed | true (futura decisión humana) | no |
| automatic | rejected | false | no |
| automatic | uncertain | false | sí |

El origen NO cambia al confirmar. `declared` ya es aceptación del sujeto, no
confirmación técnica independiente. Los hallazgos se guardan en
`Entity.metadata_info.provenance` como `automatic/discovered` aunque exista un
seed con el mismo alias: declarar alias/plataforma no confirma una cuenta
automáticamente. EntityRead expone procedencia tipada; lecturas de hallazgos
históricos sin este campo proyectan discovered sin mutar la BD.

Una observación atómica `email/phone/username` cuyo valor normalizado YA es un
seed conserva origen automático, pero lleva `matches_declared_identifier=true`
y `needs_review=false`: analizar el formato de un teléfono declarado no es
descubrir otro teléfono. No se reclasifica el análisis como declarado ni se
afirma su contenido técnico por el sujeto. La exención nunca aplica a cuentas,
documentos o brechas, aunque su consulta/alias coincida con un seed.

La persistencia compartida impide que herramientas/LLM escriban confirmed a
través de metadata; conserva decisiones ya persistidas al enriquecer. Los
pivotes extraídos siguen en `discovered_*` con evidencias de observaciones y
Frontier. No se introduce un segundo registro de identidades ni se usa el estado
de exploración pending/explored como estado de verificación humana.

Contrato para el futuro Verification Gate: filtrar por
`ownership_review_required` para cuentas y `provenance.needs_review` para otros
hallazgos (contrato Fase 2.1), nunca sobre `declared_seeds`.
No hay todavía pantalla ni endpoints de revisión. `DigitalFootprintDataset`
deberá combinar declared + confirmed con IDs de evidencia, excluyendo rejected,
discovered y uncertain del conjunto atribuido. IA tendrá procedencia separada
de las decisiones del sujeto, nunca origin=subject/automatic confirmado.

## Fase 2 — Apify Social Layer (implementada)

Base de esta fase: `b7f90f6e892d9b48e05e7c3ebfe5b83f86b845c9`; Foundation V2
se conserva, no se reimplementa. Ver [arquitectura, evaluación y límites](APIFY.md).

- Capa desacoplada `social/`: specs/matriz, router, cliente REST y parsers.
  BaseTool `apify_social` registrada en el pipeline común, sin otro almacén de
  evidencias. Inputs, datasets, outputs y errores están acotados y son mockeables.
- Ocho Actors prioritarios evaluados mediante Store/README/esquemas: Instagram,
  TikTok, Threads y YouTube integrados; Reddit/X/LinkedIn diferidos; el Actor
  Facebook evaluado sirve Pages, no perfiles personales. Sin reemplazar fuentes
  nativas ni alterar pesos/semántica de correlación.
- Router native-first: namespace prioriza, no confirma. Requiere observación
  nativa plausible y admisión de Frontier antes de enriquecer; un username sin
  plataforma no se expande ciegamente a todos los Actors. SearchDorker conserva
  sus filtros; solo sus URLs exactas de perfil con match literal son candidatas.
- Desactivado por defecto; token backend + plataformas permitidas + consentimiento
  general explícito. Se mantienen SearchDorker, GHunt, OpenAlex/Crossref, Maigret/
  WhatsMyName, GitHub, Gravatar, email, brechas, teléfono y documentos.
- Procedencia `collection_sources` con actor/run/dataset/build, URL, fecha e input
  allowlisted; persistencia común `automatic/discovered`, ownership unverified.
  Contenido público estructurado en metadata, sin IA ni extracción de privados.
- Límites por expediente de Actors/runs/filas/cargos reservados, tiempos,
  reintentos GET y paralelismo. `force` no borra reservas. Runtime existente
  persistido; no hay todavía ledger pre-POST resistente a crash duro ni límite
  distribuido. Los starts ambiguos no se reintentan y los conocidos se abortan
  best-effort al cancelar. Es una limitación documentada, no una garantía oculta.
- `GET /api/v1/sources/social` y contexto MCP permiten inspección sin secretos.
  Compose deja de inyectar `.env` backend en frontend; no cambia su diseño.
- Validación del catálogo/API: **validated**. Integración y normalización:
  **fixture-tested**. Scraping/coste/latencia comparados: **not live-tested**.
  Ningún Actor real/pagado se ejecutó; no se inventan métricas.

Fases 3–7 continúan pendientes. No se introduce SLA, orquestador Lite completo,
Verification Gate, Exposure Lens, reconstrucción IA ni rediseño del grafo/frontend.

Validación de Fase 2: 205 casos de integración/regresión (73 nuevos de Apify),
17 pruebas PostgreSQL/REST/MCP, 205 de fuentes nativas y 63 de Maigret/WhatsMyName
aprobados. Frontend: seis pruebas y TypeScript sin errores. Los detalles de la
suite general, límites y ausencia de scraping real están en `APIFY.md`.

## Fase 2.1 — Fair Routing & Live Validation

Implementada sobre `b20b045c08c142646e1ea800e0a04d28732a0c74`, misma rama.
Esta sección sustituye las decisiones de routing/presupuesto de Fase 2 arriba.
Arquitectura intacta: SocialSourceRouter → ApifySocialTool → ApifyClient →
ApifyAdapter → ToolFinding. [Detalle y comandos reproducibles](APIFY.md#fase-21--fair-routing--live-validation).

- Username declarado + plataforma integrada permite Apify inmediato con consentimiento,
  allowlist y presupuesto. Las fuentes nativas siguen elegibles para descubrir más.
  No requiere observación nativa ni Frontier para esa cuenta declarada.
- Username sin plataforma y candidatos automáticos conservan native-first +
  observación plausible + admisión Frontier. No hay expansión pagada a ciegas.
- Ownership separado: `subject_declared`, seed estable y revisión de ownership
  desactivada solamente para coincidencia exacta de username/plataforma declarada.
  Persistencia recalcula desde el target; otros perfiles y pivotes siguen unverified.
  Perfil y contenido observado continúan automatic/discovered, sin convertir posts
  en subject ni inferir atribución de terceros. Gate futuro consulta el flag de
  ownership para cuentas; no se implementa esa fase.
- Batches por plataforma/Actor/build con correspondencia por handle/ID observado,
  provenance individual y fallos parciales por perfil. Los cuatro Actors integrados
  aceptan múltiples entradas; un batch es un run y reserva todos sus perfiles.
- Nuevos defaults: 3 perfiles por Actor/investigación y 10 contenidos por perfil.
  Instagram/Threads retornan perfiles con posts anidados recortados localmente;
  TikTok/YouTube limitan contenido remoto por perfil y filas del batch. La antigua
  variable MAX_ITEMS queda obsoleta. Persisten cuotas de Actors/runs/USD, timeout,
  paralelismo, reservas y prohibición de retry del POST ambiguo.
- Integrados: Instagram `apify/instagram-profile-scraper`, TikTok
  `clockworks/tiktok-profile-scraper`, Threads `apify/threads-profile-api-scraper`,
  YouTube `streamers/youtube-channel-scraper`. Solo Instagram/TikTok en allowlist
  por defecto; todos dependen del flag global (false por defecto).
- Reddit oficial `apify/reddit-scraper` reevaluado como prioridad alta: usernames,
  perfil y modos posts/comments acotados permiten evaluar actividad pública útil.
  Sigue native/deferred porque no hay token para demostrar funcionamiento y mejora
  real. Benchmark incluye sus tres modos. Se abandona la evaluación exclusiva del
  Actor comunitario anterior. [Contrato oficial](https://apify.com/apify/reddit-scraper/input-schema).
- X `apidojo/twitter-profile-scraper`: contrato actual revisado (handles, tweets,
  replies opcionales, límite global); probe mínimo preparado sin extras. Sigue
  native/deferred sin datos reales de latencia/calidad/coste.
  [Contrato actual](https://apify.com/apidojo/twitter-profile-scraper/input-schema).
- LinkedIn sigue diferido; Facebook sigue nativo por contrato de Pages públicas.
  SearchDorker/Maigret y todos los especialistas fuertes siguen disponibles.
- Live validation ejecutada el 16-10-2026: un perfil público `apify` por cada uno
  de los cuatro Actors integrados; límite USD 0.02/run y USD 0.08 total reservado.
  Instagram/TikTok/YouTube observaron perfiles; TikTok/YouTube devolvieron un vídeo
  útil cada uno. Threads run `SUCCEEDED`, pero indicó `isProfileNotExist`; no se
  valida ese perfil/Actor para la feria. UsageTotalUsd informado: Instagram 0,
  TikTok 0.003, Threads 0.005, YouTube 0 USD; suma USD 0.008 informada (no factura
  final garantizada). Latencias: 6.03, 20.50, 48.76 y 23.09 s respectivamente.
  Builds fijados: Instagram `0.0.643`, TikTok `0.0.489`, YouTube `0.0.248`.
  [Informe con run/build IDs y schema](audits/apify-phase21-validation-2026-10-16.json).
- Reddit/X permanecen diferidos y no se ejecutaron en la tanda de cuatro runs;
  el script `backend/scripts/apify_live_benchmark.py` incluye probes explícitos
  con cuotas pequeñas y reportes sin filas crudas.
- Riesgos para Fase 3: confirmar cargos en Console, conseguir contenido Instagram y
  una cuenta de prueba Threads pública válida, medir Reddit/X y mantener el ledger
  transaccional pre-POST y la coordinación multi-worker pendientes.
  Los límites del benchmark son por invocación, no un ledger entre informes distintos.

Validación Fase 2.1: **91 pruebas Apify/benchmark**, **18 PostgreSQL/REST/MCP**
y **1017 regresiones generales** aprobadas (19 excluidas por marcadores;
se omite `test_scan_progress.py`, sin modificaciones). La prueba de compatibilidad
con reservas antiguas se añadió tras la colección general y está entre las 91.
`git diff --check` sin errores. Las corridas restringidas bloqueadas se interrumpieron;
las corridas generales/BD aprobadas se ejecutaron fuera del sandbox.

No se implementan Orchestrator Lite, SLA, Gate UI, Exposure Lens, IA, Graph V2 ni frontend.

## Fase 3 — PersonMap Lite Orchestrator (pendiente)

Modo acotado de aproximadamente 3–4 minutos: breach checker, GHunt, búsqueda,
OpenAlex/Crossref, GitHub, Gravatar, teléfono, correo rápido y Maigret Lite.
Conservar registry, dispatch, cobertura, trazas y persistencia. Añadir presupuesto
global/cancelación y reservar segunda oleada para nuevos emails/alias y Apify.
No modificar hoy presets ni prometer ese tiempo con motores actuales.

## Fase 4 — Verification Gate (pendiente)

Al terminar el descubrimiento: SOLO elementos nuevos con Sí soy yo / No soy yo /
No estoy seguro. Transiciones authenticated/auditadas a confirmed/rejected/uncertain,
con fecha y evidencia; no sobrescribir origen. No presentar seeds para reconfirmar.
Producir un dataset limpio y mantener separada verificación de existencia.

## Fase 5 — Exposure Lens (pendiente)

Analizar progresivamente posts, captions, bios, comentarios públicos, hashtags,
menciones y metadata pública. Detectar exposición de ubicación general,
instituciones, contexto profesional/académico, rutinas, biografía, contactos,
alias reutilizados y documentos útiles para ingeniería social/correlación.
Cada señal explica QUÉ revela y POR QUÉ aumenta exposición, con URL/fragmento y
alcance de atribución. Antes de confirmación, analizar contenido como candidato,
no como hecho de la persona; no inferir información sensible sin evidencia.

## Fase 6 — Digital Footprint Reconstruction + Graph V2 (pendiente)

Acción explícita «Reconstruir mi huella digital». IA recibe JSON estructurado de
declarados, confirmados, evidencias públicas y Exposure Lens; nunca un volcado
atribuido de candidatos rechazados/no revisados. Separar `OBSERVED`, `DECLARED`,
`CORRELATED`, `INFERRED` y referenciar evidencia en cada inferencia.
Reconstrucción explicable de hechos, actividad académica/profesional, intereses
públicos, tecnologías, instituciones, ubicación general sustentada, alias,
cuentas correlacionables, exposición, ingeniería social y recomendaciones.
Grafo persona → identificadores → cuentas → contenido/documentos/brechas →
inferencias. No porcentajes engañosos de probabilidad de identidad.

## Fase 7 — Frontend Fair Edition (pendiente)

Fase dedicada de presentación: formulario limpio, progreso/fuentes activas,
descubrimientos, Verification Gate, Exposure Lens, mapa renovado, pantalla
«Tu huella digital pública», exposición, animaciones discretas, estados vacíos,
fallos parciales, modo demo y responsive. Quitar ruido técnico sin ocultar
incertidumbre ni fallos. La entrega actual solo adapta formulario/contratos V2;
no implementa el rediseño completo ni presenta funciones aún inexistentes.

## Riesgos y decisiones para próximas sesiones

- Muchos seeds no equivalen a búsqueda exhaustiva: continúan los presupuestos
  existentes (alias/teléfonos, GHunt, consultas web y APIs). No ampliarlos sin
  medición para la demo. Una plataforma etiquetada no restringe motores actuales.
- GHunt depende de la sesión del operador y la disponibilidad de cada fuente
  no se valida con fixtures. Apify requerirá medición real de coste/latencia,
  licencias, términos y minimización/retención del contenido público.
- V1 no adquiere obligatoriedad general de consentimiento para no romper
  clientes históricos. Retirar esa entrada o endurecerla requiere versión/política
  de deprecación explícita; ninguna herramienta puede inferir consentimiento.
- La revisión humana futura necesita endpoints y autorización propios; el
  contrato de estados no es una implementación de esas transiciones.
- Mantener evidencia original, historial de decisiones y no transmitir
  atribuciones entre cuentas por compartir alias o componente de grafo.
- No se incluye `opencode.json` preexistente sin seguimiento en este commit.

## Validación de Foundation V2 (Fase 1)

Ejecutado el 15-10-2026, con identidades ficticias y sin consultas OSINT reales:

```bash
cd backend
.venv/bin/python -m pytest -q --durations=10
.venv/bin/python -m pytest tests/test_footprint_foundation.py tests/test_schemas.py tests/test_agent_fallback.py tests/test_hybrid_engine.py tests/test_pivot_frontier.py tests/test_correlation_evidence.py tests/test_persistence.py tests/test_resolver.py -q
.venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
cd ../frontend
pnpm test:footprint
pnpm test:graph
pnpm exec eslint src/components/investigation/InvestigationForm.tsx src/lib/footprintInput.ts src/lib/types.ts
pnpm exec tsc --noEmit
pnpm build
```

- Suite general final: **932 aprobadas, 18 excluidas** por los marcadores de
  red/BD (541,95 s). La integración PostgreSQL se ejecutó aparte. Una primera
  ejecución con límite de 120 s se interrumpió; al ampliar el plazo la suite
  terminó correctamente. La mayor parte del tiempo corresponde a pruebas
  existentes de progreso del escaneo, no a los nuevos contratos V2.
- Suite específica: **133 aprobadas**, incluidos múltiples datos iniciales,
  plataforma libre/ausente, normalización, deduplicación, procedencia,
  reanálisis de identificadores declarados sin reconfirmación, no atribución de
  cuentas, conservación de decisiones humanas, consentimiento, serialización,
  round-trip V1/V2, TargetContext, barrido con/sin Frontier e híbrido.
- PostgreSQL/REST/MCP: **16 aprobadas**. Se usan esquemas temporales con
  migraciones reales; se comprueba recarga sin caché y expedientes históricos.
- Regresión específica de fuentes: **205 aprobadas** (`test_search_dorker`,
  `test_search_coverage`, `test_search_resilience`, `test_academic_engine`,
  `test_academic_evidence`, `test_ghunt`, `test_phone_engine`,
  `test_github_deep_scanner`, `test_infostealer_checker`).
- Maigret/WhatsMyName: **63 aprobadas** (`test_maigret_capabilities`,
  `test_maigret_integration`, `test_username_finder_wmn`).
- Frontend: **2 pruebas de entrada + 4 del grafo aprobadas**, ESLint de los
  archivos afectados y TypeScript sin errores; build de producción correcto.
- Smoke HTTP/SSR contra `/auditorias/nueva` en un servidor Next de producción
  temporal: nombres/apellidos, correo, teléfono, plataforma libre, botones de
  listas y consentimiento `required` presentes; sin DNI/ORCID/descripción en el
  formulario. No sustituye una prueba de interacción en navegador real.
- Los scripts Node emiten el aviso preexistente `MODULE_TYPELESS_PACKAGE_JSON`;
  no se cambia el modo de módulos del proyecto para silenciarlo.
- `git diff --check` sin errores. No se han probado disponibilidad de fuentes
  externas ni tiempos Lite: eso no forma parte de Foundation V2.
