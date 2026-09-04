# Plan de ejecución — PersonMap: de P0 a "world-class"

> **Documento vivo.** Actualiza el estado al cerrar cada fase.
> Rama de trabajo: `mejoras`.

---

## ESTADO — actualizado 2026-09-04

| Fase | Estado | Commit |
|---|---|---|
| 0 · Estabilización | ✅ **Completada** | `3c2f8e4` |
| 1 · Hacer visible lo que ya existe | ✅ **Completada** | `3021b53` |
| — · Tavily para dorking *(añadido a petición)* | ✅ **Completada** | `3021b53`, `6a85719` |
| 2 · Corregir el modelo de identidad | ✅ **Completada** | `941b5a5`, `d3cc158` |
| 3 · `hybrid` como tercera estrategia | ✅ **Completada** | `da1cb85` |
| 4 · Cobertura de fuentes | ⬜ Pendiente | — |
| 5 · Cosecha activa de avatares | ⬜ Pendiente | — |

**Línea base al retomar:** 94 tests en ~25 s sin red · `tsc` limpio · backend `:8000` y frontend `:3000`.

### Cómo retomar en otra sesión

1. `cd "C:\octavo\seguridad de la info\proyecto\PersonMap"` y `git checkout mejoras`.
2. Levantar: `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
   y `cd frontend && pnpm dev`.
   **`--reload` no funciona en esta ruta** (StatReload se cuelga a medias con
   los espacios del path en Windows): hay que reiniciar el backend a mano tras
   tocar Python.
3. Leer este fichero y "Correcciones aprendidas" antes de abrir la fase siguiente.
4. Re-verificar las fuentes externas con `curl` y anotarlo en
   [`OSINT_SOURCES.md`](./OSINT_SOURCES.md) — se degradan sin avisar.

`uv` está instalado en `%APPDATA%\Python\Python311\Scripts` y **no está en el
PATH**; hay que añadirlo en cada shell.

---

## Correcciones aprendidas durante la ejecución

Cosas que el plan original daba por buenas y que la realidad desmintió. Merecen
leerse antes de seguir, porque cambian decisiones de las fases pendientes.

**El modelo de identidad no decidía nada.** No era solo que las señales sin dato
penalizaran: el `max(f.confidence, score)` descartaba el resultado del modelo
*siempre*, porque las herramientas emiten constantes de 0.85-1.0 y el modelo
saturaba en 0.45. Sobre 392 entidades reales, el `identity_score` era 0.45 en
las 392. Cualquier trabajo sobre señales nuevas habría sido inútil sin arreglar
esto primero.

**Las tautologías son el enemigo principal, y aparecen en tres capas.** En el
grafo (aristas `same_username` entre hermanos de enumeración: 3835 → 117
aristas), en el scorer (la señal de alias), y en la propia URL (contener el
alias buscado no es evidencia; sin esa corrección
`xboxgamertag.com/search/<alias>` puntuaba 0.99). **Al añadir cualquier fuente
nueva, preguntar siempre: ¿esta coincidencia está garantizada por cómo busqué?**

**Los tests con mock no bastan para una API externa.** Los 10 tests de Tavily
pasaban mientras la integración real devolvía cero resultados: su parámetro
`exact_match` está documentado pero rompe en producción, y su búsqueda es
semántica (un correo inexistente devuelve la portada de su dominio). **Toda
fuente nueva debe verificarse en vivo con `curl` antes de darla por integrada.**

**`uvicorn --reload` no es fiable aquí.** Varias medidas salieron mal hasta
descubrir que el backend servía código viejo. Reiniciar a mano y confirmar en el
log que el arranque completó.

**`npx next lint` ya no existe** (Next 16 lo retiró: devuelve *"Invalid project
directory provided, no such directory: .../lint"*). El comando real es
`npx eslint src`, y su **línea base son 19 errores preexistentes** (`no-explicit-any`
y `react-hooks/set-state-in-effect`, sobre todo en `DigitalMapGraph`). No son
regresiones: para saber si una tanda de cambios introduce alguno, comparar contra
esa cifra con `git stash`.

**La capa IA se puede verificar en vivo sin clave de proveedor.** LiteLLM
respeta `OPENAI_BASE_URL`, así que un servidor OpenAI-compatible de tres
funciones en `localhost` permite ejercitar el camino HTTP completo — esquema de
funciones, parseo de `tool_calls`, secuencia `assistant`/`tool` del segundo
turno — que es justo donde los mocks no llegan. **No sustituye a una prueba
contra un proveedor real** (la lección de Tavily fue que el fallo estaba en el
comportamiento del proveedor, no en el formato), pero cubre todo lo demás.

**crt.sh está degradado y hay que planificarlo.** Medido el 2026-09-04: 1 de 4
peticiones devolvió HTTP 200 y las otras tres, 502. Afecta directamente a la
Fase 4.4: sin reintentos con espera no se puede depender de él, y en una
sustentación en vivo es una fuente que se cae delante del jurado.

**Los eventos de progreso de las tools no llevan capa.** `username_finder`
publica su `phase: "progress"` directamente al bus, sin pasar por el motor, así
que en una corrida híbrida esas líneas salen sin `layer`. La consola les reserva
el hueco del distintivo para no romper la alineación. Si en la Fase 4 se cablea
la barra de progreso real (M2), conviene propagar la capa hasta la tool.

### Correcciones al plan de las fases pendientes

- **Fase 4 — el presupuesto de concurrencia es bloqueante, no una nota.** Medido:
  una investigación con pivoteo tarda **385 s** porque `username_finder` acapara
  el semáforo global de 40 peticiones. Subir el catálogo a ~2700 sitios sin
  repartir ese presupuesto por herramienta llevará la investigación a decenas de
  minutos, inviable para una sustentación en vivo. Mitigación inmediata para
  demos: bajar `USERNAME_SCAN_MAX_SITES` en `.env` (con 60 sitios, ~40 s).
- **Fase 5 — la denylist de avatares por defecto sigue siendo obligatoria**, pero
  el riesgo bajó: ya no existe el atajo `confidence = max(conf, 0.99)` que
  convertía una coincidencia de avatar en "identidad confirmada" saltándose el
  modelo. Ahora entra como una señal más, ponderada.
- **La señal semántica está lista pero inactiva.** `enrichment.py` la calcula si
  se configura `LLM_EMBEDDING_MODEL`; sin él degrada a cotejo léxico.
- **Fase 4 — el filtro anti-repetición del híbrido depende de la clave de
  ejecución.** `RuleEngine._get_tool_run_key` es hoy la única frontera entre "el
  híbrido refina" y "el híbrido repite el barrido entero". Toda tool nueva debe
  declarar bien sus `required_inputs`, o su clave no distinguirá dos llamadas
  distintas y la capa 2 saltará trabajo que sí hacía falta (o repetirá el que no).
- **El expediente `d2c282f8` es dato de verificación, no muestra.** Se creó para
  probar la capa 2 contra un LLM simulado, y su hallazgo de GitHub lo pidió el
  stub, no un modelo real. Conviene borrarlo antes de recoger las cifras
  definitivas del artículo.

---

## Context

`ANALISIS_OSINT_MUNDIAL.md` (2026-09-03) auditó el proyecto contra el estado del arte OSINT mundial y produjo una hoja de ruta de 20 ítems en 4 tramos (P0→P3). El commit `9e4e9ce` ejecutó **el tramo P0 completo** (5/5). De P1/P2/P3 no se ha empezado nada.

Este plan cubre lo que falta, bajo tres objetivos simultáneos declarados por el usuario: **sustentación de curso** (la demo debe verse impecable), **artículo científico** (métricas reproducibles y defendibles), y **producto que seguirá creciendo**.

### Dos problemas de fondo descubiertos al preparar este plan

**1. Deuda de integración del batch P0.** El backend ya emite tres `entity_type` nuevos — `image_match`, `google_account`, `academic_profile` — que no tienen **ninguna** representación en el frontend (ni filtro, ni capa en el mapa, ni icono: caen en el `Globe` gris genérico) y que además suman **cero** al scorecard de exposición, porque `identity/risk.py` solo pondera `social_account`, `email`, `academic`, `search_mention`, `breach` y `phone`. Es exactamente el fallo que el usuario quiere evitar: capacidad interna invisible.

**2. El motor de correlación no está decidiendo nada.** Verificado numéricamente ejecutando la fórmula de `scorer.py` con sus propios parámetros:

```
Caso base (7 señales, todos γ=0):  LLR = −31.60 bits  →  posterior ≈ 6.3e−12  →  clamp a 0.05
Match fuerte de nombre (γ=0.8):    LLR = −22.67 bits  →  posterior ≈ 0        →  override a 0.45
```

Tres consecuencias encadenadas:

- **La distribución de scores es trimodal `{0.05, 0.45, 0.95}`**, no continua. El `CONFIRMED_THRESHOLD = 0.70` del resolver es **inalcanzable por la vía Fellegi-Sunter**; solo se cruza por el override `max(posterior, 0.95)` de `scorer.py:127-128`.
- **La causa raíz es metodológica: "dato ausente" se codifica como "desacuerdo".** Si el objetivo no tiene teléfono, `phone_match = 0.0` y el modelo cobra −4.32 bits por un campo que nunca se pudo observar. Fellegi-Sunter estándar tiene **tres** estados (acuerdo / desacuerdo / *missing* → peso exactamente 0). Esto es un error citable en revisión por pares.
- **Y el score se descarta de todos modos.** `rule_engine.py:141` y `autonomous_agent.py:194` hacen `final_conf = max(f.confidence, score)`, y las tools emiten confianzas fijas de 0.85–1.0. Como el score real vale 0.05 o 0.45, el `max()` **lo tira siempre**. El resolver luego clusteriza sobre `e.confidence`.

> **Hoy los clusters de identidad los decide un número escrito a mano en cada tool, no el modelo probabilístico que va al artículo.**

Esto reordena el plan: añadir señales nuevas (embeddings, avatar) a un modelo cuyo output se descarta es trabajo desperdiciado. **Primero hay que hacer que el score importe.**

---

## Principios rectores

### 1. No reinventar la rueda

Antes de escribir cualquier módulo nuevo, buscar si ya existe. Orden de preferencia:

1. **Reusar el dato** (dataset de otro proyecto, con su licencia y atribución).
2. **Portar la técnica** (endpoint + heurística, reimplementados sobre nuestra `http_client`).
3. **Construir desde cero** — solo si no existe.

Nunca añadir el binario de otra herramienta como dependencia de ejecución: la arquitectura `BaseTool` + `ToolRegistry` + capa HTTP resiliente se rompería. Se trae el dato o la técnica, no el proceso.

### 2. Vigilancia continua del ecosistema

El ecosistema se degrada rápido (Holehe lleva años sin mantenerse y tiene módulos rotos). Es una **práctica permanente**, no una tarea:

- Antes de abrir cada fase, revisar el estado de `soxoj/maigret`, `WebBreacher/WhatsMyName`, `kaifcodec/user-scanner`, `megadose/ignorant`, `mxrch/GHunt`, y las listas `jivoi/awesome-osint` y `edwardtay/awesome-OSINT`.
- Registrar cada revisión en un fichero vivo **`docs/OSINT_SOURCES.md`**: fuente, licencia, técnica adoptada, fecha de última verificación, estado (operativa / degradada / muerta).
- Anotar en el docstring de cada módulo el repo de origen y su licencia, como ya hacen `http_client.py` y `google_account_osint.py`.

### 3. Toda mejora de backend lleva su mejora de frontend emparejada

**Criterio de aceptación: ninguna tarea termina si su resultado no es visible, filtrable y legible en la UI.** Un `entity_type` nuevo exige como mínimo: icono propio, entrada en los filtros de `FindingsTable` **y** de `DigitalMapGraph`, estilo de nodo diferenciado, **y ponderación en `risk.py` con su recomendación pedagógica**.

### 4. Restricciones del usuario

- **Solo fuentes gratuitas y sin API key.** Descartados HIBP, SerpApi y Brave Search API. Esto redefine los ítems P1#6 y P1#9 del análisis y obliga a resolver el reverse-image-search por otra vía (Fase 5).
- **Embeddings vía `litellm.aembedding`** (verificado disponible en litellm 1.99.0), degradando a fuzzy si no hay LLM.

---

## Punto de partida

Rama `mejoras`, sincronizada con `origin/main` en `9e4e9ce`. Cambios **sin commitear** que hay que consolidar antes de empezar:

- `.gitignore` — la regla `lib/` (patrón Python) ocultaba también `frontend/src/lib/`, por lo que `api.ts` y `types.ts` nunca se commitearon y el frontend no compilaba en un clon limpio. Corregido a `/lib/` y `/lib64/`.
- `frontend/src/lib/api.ts` y `types.ts` — reconstruidos desde los schemas Pydantic. `tsc --noEmit` limpio.

Línea base: backend `:8000` y frontend `:3000` en HTTP 200; `uv run pytest` da **16 passed** (~3 min).

---

## Fuentes gratuitas verificadas en vivo (2026-09-03, con `curl`)

| Fuente | Endpoint | Key | Resultado |
|---|---|---|---|
| **Hudson Rock Cavalier** | `cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email\|username\|domain` | **No** | HTTP 200 con datos reales: `stealers[]` con `date_compromised`, `computer_name`, `operating_system`, `malware_path`, `total_user_services`. Límite documentado **50 req/10 s por host** |
| **crt.sh** | `crt.sh/?q={dominio}&output=json` | **No** | HTTP 200 |
| **Avatar GitHub** | `github.com/{user}.png` | **No** | HTTP 200, `image/jpeg` |
| **Avatar Gravatar** | `gravatar.com/avatar/{md5}?d=404` | **No** | HTTP 200 (404 si no existe → señal binaria limpia) |
| **Maigret `data.json`** | `raw.githubusercontent.com/soxoj/maigret/main/maigret/resources/data.json` | **No** | MIT. **3653 sitios**, 693 `disabled` → **2960 utilizables**; 278 con `protection` (TLS fingerprint, a saltar); 1156 con `alexaRank`; 163 con `regexCheck` |

`unavatar.io` queda **descartado como dependencia de runtime** (25 req/día por IP en anónimo). Se usa solo como *referencia* de su lista open-source de proveedores.

---

## Fase 0 — Estabilización ✅ COMPLETADA (`3c2f8e4`)

> **Resultado medido:** aristas del grafo 3835 → 117 (−97%) sin perder ningún
> hallazgo; suite de tests 194 s → 6.5 s y ya no requiere Internet.


Prerrequisitos duros. Nada de lo que sigue es seguro sin esto.

### Backend

| Tarea | Por qué |
|---|---|
| **`MutableDict.as_mutable(JSONB)`** en los modelos | `resolver.py:45` escribe `metadata_info["avatar_correlated"] = True` **después** del flush; sin `MutableDict` ese flag **se pierde siempre**. La UI nunca podrá mostrar "correlacionado por avatar". Cambio de una línea, **sin migración** |
| **Extraer `persist_findings()` + `build_relationships()`** a `app/engine/persistence.py` y llamarlo desde ambos motores | `autonomous_agent.py:212-233` duplica la persistencia en versión degradada (sin dedup, sin `_detect_relationship`, sin pivoteo). Son ~40 líneas movidas sin cambio de comportamiento, y el agente hereda **gratis** lo que hoy le falta. Sin esto, **cada cambio de las fases 2–5 se paga dos veces** |
| **Quitar el fallback `same_platform` de `_detect_relationship`** (`rule_engine.py:240-241`) | Es O(n²) sobre todas las entidades y su último caso empareja cualquier par con la misma plataforma — incluido `None == None`. Con ~30 entidades son 450 pares; **al escalar a 500 entidades son 125.000 pares y decenas de miles de aristas sin significado**. El mapa se vuelve una bola de pelo ilegible y el `flush` de relaciones, el cuello de botella. **Prerrequisito duro de la Fase 4** |
| **`avatar_hasher.py` → `http_client`** | Crea su propio `httpx.AsyncClient(..., **`verify=False`**)`: fuera del semáforo global, fuera del backoff, fuera de la rotación de UA, y **con verificación TLS desactivada en un proyecto de seguridad de la información**. Un jurado que abra ese fichero lo va a ver |
| **Cap del `_history` del EventBus** + purga al completar | Crece sin límite y nunca se purga. Añadir aviso en arranque si `workers > 1` (el bus es in-process; el SSE se rompe en silencio) |

### Frontend

- **Centralizar las 5 URLs hardcodeadas** que se saltan `lib/api.ts`: `Navbar.tsx:11` (health), `LiveConsole.tsx:29,49` (logs, stream), `DigitalMapGraph.tsx:216` (graphml), `EvaluationView.tsx:57` (metrics).
- **Crear `error.tsx`, `loading.tsx`, `global-error.tsx`** (App Router) — hoy inexistentes, igual que cualquier Error Boundary.
- **Estados de error honestos.** Hoy la UI miente cuando algo falla: `EvaluationView.tsx:60` renderiza un dashboard de **ceros sin aviso** en una pantalla titulada "Módulo de Evaluación para Artículo Científico"; `InvestigationHistory.tsx:28` traga el error con `.catch(() => setInvestigations([]))` y muestra "No hay investigaciones registradas" cuando el backend está caído.
- **`LiveConsole`:** quitar el `eventSource.close()` del `onerror` (L78-81), que **cancela deliberadamente la reconexión nativa de `EventSource`**. Y colorear por `phase`, no por `type` — hoy `agent_error` viaja con `type: "log"` y **se pinta en gris**.
- **Clases inexistentes:** `animate-in` / `slide-in-from-right` / `fade-in` son de `tailwindcss-animate`, dependencia **ausente de `package.json`** (`DigitalMapGraph.tsx:306`, `InvestigationForm.tsx:189`, `EvaluationView.tsx:225`). También `py-0.2` (`DiscoveryTimeline.tsx:43`) no existe en la escala de Tailwind.
- **Bug de layout del grafo:** el panel de detalle usa `w-80 border-l shrink-0` (`DigitalMapGraph.tsx:305`) dentro de un contenedor `flex flex-col` → se renderiza apilado debajo del canvas y recortado por `h-[680px] overflow-hidden`.

### Tests

Añadir **`respx`** al grupo dev (mock de transporte nativo de httpx, encaja con `ResilientTransport`). Reestructurar:

```
tests/
  unit/          # sin I/O: scorer, adaptador de datasets, union-find, dHash
  integration/   # tools con respx + fixtures grabadas
    fixtures/<tool>_hit.html, <tool>_miss.html, <tool>_ratelimited.json
  e2e/           # @pytest.mark.network, deseleccionado por defecto
```

En `pyproject.toml`: `addopts = "-m 'not network'"`, `markers = ["network", "db"]`. Hoy **no hay ningún mock** y `test_e2e.py` golpea PostgreSQL real e Internet real.

**Verificable por:** el sistema nunca miente al usuario cuando algo falla, y la suite corre sin Internet.

---

## Fase 1 — Hacer visible lo que ya existe ✅ COMPLETADA (`3021b53`)

> **Resultado medido:** los 3 `entity_type` huérfanos ya tienen icono, filtro,
> color de nodo y peso en el scorecard. La encuesta captura datos: verificada
> end-to-end con delta de concienciación +3.00. Se añadió además Tavily como
> motor de dorking, a petición del usuario (ver `6a85719`).


**Máximo retorno, riesgo de backend ≈ 0.** Es la fase que hace que la sustentación se vea impecable y no toca ni un algoritmo.

### Backend (mínimo)

Emitir el `breakdown` del scorer **dentro de `metadata_info`** al construir la `Entity` (antes del flush, donde `MutableDict` no aplica porque el dict se pasa completo al constructor). Hoy el `breakdown` **se descarta** en los dos call-sites y es el dato más rico del modelo. **Cero migración.**

Ponderar los tres `entity_type` huérfanos en `risk.py` con su recomendación pedagógica.

### Frontend

| Tarea | Detalle |
|---|---|
| **Módulo compartido `lib/entityTypes.ts`** | La lista de categorías está **duplicada y divergente**: `FindingsTable.tsx:28-37` tiene 8 entradas, `DigitalMapGraph.tsx:219-226` tiene 6. Esa duplicación es la causa raíz de los tipos huérfanos; centralizarla evita que se repita con cada tipo nuevo |
| **Representar los huérfanos** | `image_match`, `google_account`, `academic_profile` con icono, color de nodo y filtro en ambas vistas. Añadir `search_mention` y `document` al filtro del grafo. Ampliar `getPlatformIcon` (`DigitalMapGraph.tsx:38-51`), que no cubre facebook, tiktok, youtube, reddit, telegram, keybase, gravatar ni wikipedia — plataformas que las tools ya producen. Dar estilo de nodo por tipo (hoy solo `breach` y `phone` lo tienen). Eliminar las ramas muertas de `FindingsTable.tsx:21-22` |
| **Panel "¿Por qué creemos que es esta persona?"** | Desglose del breakdown por señal y su peso en log-likelihood. Convierte una caja negra que escupe "87%" en una explicación auditable — el tipo de evidencia que defiende un tribunal y sostiene un artículo |
| **Encuesta de concientización viva** | Ver abajo |
| **`@theme` de Tailwind v4 + estilos `print:`** | Ver abajo |

### La encuesta: la variable dependiente del artículo, hoy sin capturar

El backend está **completo** (`POST /api/v1/surveys`, `GET /api/v1/surveys/stats` con el delta pre/post, modelo `AwarenessSurvey`, registrado en el router). El frontend es una **maqueta muerta**: los `<input type="radio">` de `EvaluationView.tsx:224-268` no tienen `value`, ni `checked`, ni `onChange`, ni estado, ni `<form>`, ni botón de envío. `preTestScore`/`postTestScore` (L52-53) se declaran y nunca se usan. Faltan `investigation_id`, `pre_awareness` y `post_awareness`, que el POST exige.

**El proyecto no está capturando su propia métrica pedagógica.** Sin esto no hay dato de "antes vs después" que reportar. Añadir `createSurvey` y `getSurveyStats` a `lib/api.ts` (no existen), cablear el formulario, visualizar el delta agregado.

### Informe imprimible

`globals.css` **no tiene ninguna regla `@media print`**; solo hay dos utilidades `print:` en todo el proyecto. Como los fondos son `background-color` y los navegadores no los imprimen por defecto, el informe sale con **texto gris claro sobre papel blanco, prácticamente ilegible**, y no se ocultan Navbar, footer ni la barra de tabs. Una hoja de impresión completa es mucho más barata que generar PDF server-side (P3#17) y resuelve el 90% del problema.

Además, el bloque `@theme` de Tailwind v4: hoy las variables de `:root` (L3-16) no generan utilidades, de ahí ~30 hex hardcodeados repartidos por los componentes.

---

## Fase 2 — Corregir el modelo de identidad ✅ COMPLETADA (`941b5a5`, `d3cc158`)

> **Resultado medido** sobre las mismas 392 entidades reales: `identity_score`
> pasa de 0.45 en las 392 a una distribución continua 0.010–0.990, con 26
> (6.6%) sobre el umbral y los perfiles correctos en cabeza. Conjunto
> etiquetado de 12 casos con precisión 1.00 y exhaustividad 1.00.


Corresponde a los ítems P1#11, P2#12 y P2#14 del análisis, pero reordenados: **antes de añadir señales hay que arreglar el modelo**.

### 2.1 Señales con tres estados

Registro de señales, cada una con `applicable(target, metadata) -> bool` y `gamma(...) -> float`. **Si no es aplicable, el campo no entra en el bucle** (contribución 0 bits), en vez de entrar con γ=0. Con esto el caso base pasa de −31.6 bits a **0 bits** y el posterior base = prior = 0.02. Una señal nueva deja de penalizar a nadie: es aditiva y opcional por construcción.

**Este es el único cambio que hace seguro añadir `avatar_match` y `semantic_bio_match`.**

### 2.2 Separar detección de atribución

`f.confidence` de la tool responde *"¿existe esta cuenta?"*. El score responde *"¿es de mi objetivo?"*. Son ortogonales y hoy están colapsadas en una sola columna. **Eliminar el `max()`**, guardar `existence_confidence` e `identity_score` por separado. Da un eje narrativo para el artículo y una columna extra en la UI que se explica sola.

### 2.3 Eliminar los overrides y recalibrar

- Fuera `max(posterior, 0.45)` y `max(posterior, 0.95)` (`scorer.py:125-129`). Existen solo para compensar la penalización del caso base; con 2.1 sobran. Si `cryptographic_proof` merece 0.95, su m/u ya lo expresa (+16.6 bits).
- **Recalibrar `u`.** `cross_link` con `u=0.01` afirma que solo el 1% de perfiles no-match tienen algún `linked_profiles`: es falso, debería rondar 0.4–0.6. `name_match` con `u=0.005` sobre `fuzz.partial_ratio` de un corpus que incluye la bio es optimista (partial_ratio sobre texto largo produce falsos positivos altos).
- `name_match` / `username_match` / `cross_link` **violan independencia condicional** entre sí: capar `total_weight` (±20 bits) o agruparlas.
- **`SCORER_VERSION`** en el breakdown persistido. Sin eso, investigaciones viejas y nuevas no son comparables y el artículo pierde trazabilidad.

### 2.4 Scoring en dos pasadas

No resolver el desorden avatar/scorer moviendo llamadas:

- **Pasada 1** (síncrona, barata): señales textuales sobre `metadata_info`. Donde está hoy.
- **Pasada 2** (async, en lote, tras el flush): enriquecimiento — dHash de avatares + embeddings LiteLLM **en un solo batch** — que escribe `avatar_match` y `semantic_similarity` en metadata y **re-puntúa** las entidades afectadas.

Resuelve a la vez el orden del pipeline, evita convertir `compute_identity_score` en corutina (cambio que se propagaría a los dos motores) y evita un `await aembedding` por entidad dentro de un bucle.

`semantic_bio_match` resuelve el caso "UNMSM" vs "Universidad Nacional Mayor de San Marcos", que hoy da 0 porque `university_match` compara por substring exacta (`scorer.py:55-65`).

### 2.5 Clustering real

`resolver.py` **no agrupa**: particiona por umbral en 3 clusters de etiqueta fija, ignorando las aristas de `Relationship` y los pares de correlación de avatar. Sustituir por **union-find** sobre esas aristas — el enfoque de `clawithme`, señalado en el análisis como el benchmark más cercano. **Solo funciona una vez que los scores dejan de ser trimodales.**

### 2.6 Migraciones: Alembic aquí, no antes

`create_all` no altera tablas existentes, así que añadir columnas rompe instalaciones desplegadas. En la Fase 1 se evita el problema metiendo el breakdown en `metadata_info` (compromiso consciente: no es consultable por SQL en agregado). **Aquí ese coste muerde**, porque el artículo necesita agregar sobre los scores (histogramas, curvas de calibración, ablación).

Introducir Alembic con **baseline aplanado**: `alembic stamp head` sobre la BD existente (que ya coincide con los modelos) y **una sola revisión** que añada de golpe `identity_score`, `existence_confidence`, `score_breakdown`, `scorer_version`, más los índices que faltan (**no hay ni uno**, ni siquiera en `entities.investigation_id`, que PostgreSQL no crea solo para las FK).

### 2.7 Artefactos que valen doble

- **Fixture de ground truth:** 20–40 pares `(entidad, objetivo, es_match)` etiquetados a mano. Es test de regresión **y** tabla de resultados del artículo. Se construye una vez, se usa dos.
- **Ablación con/sin embeddings**, etiquetada por `scorer_version`. Esa comparación es la contribución del artículo, no el hecho de usar embeddings.

**Frontend emparejado:** vista de clusters con la evidencia por arista; histograma de distribución de scores y curva de calibración en `EvaluationView`. La "Matriz de Correlación" (`IdentityClustersView.tsx:94-158`) hoy es cosmética — empareja cada entidad con `allEntities[(idx+1) % n]`, es decir **su vecina en el array**, no una correlación calculada; con union-find pasa a mostrar cruces reales.

---

## Fase 3 — `hybrid` como tercera estrategia ✅ COMPLETADA (`da1cb85`)

> **Resultado medido** contra la API real: una investigación `hybrid` con la capa
> IA activa registra `engine_used: hybrid`, 13 hallazgos heurísticos + 1 de
> refinamiento, **1 llamada del LLM descartada** por haberla hecho ya el barrido,
> y **1 entidad que solo existe gracias a la IA** (7,1 % del total). Sin LLM, la
> misma estrategia registra `engine_used: rules` y `hybrid_degraded: true`.

El análisis (§5.3) recomienda un orquestador híbrido: `rule_engine` siempre primero, y el LLM como capa de refinamiento. **Pero implementarlo como reemplazo del `if/else` de `orchestrator.py` destruiría una feature existente**: el commit `f2ab953` añadió el apartado de comparativas de motores, y si el rule engine corre siempre, `rules` y `agentic` dejan de ser condiciones independientes — se pierde el diseño experimental más limpio que tiene el proyecto.

**Se añadió, no se reemplazó.** Cuatro valores de `strategy` (`auto`, `rule_based`, `agentic`, `hybrid`) y tres motores comparables. Los dos brazos anteriores no se tocaron.

### 3.1 El motor de dos capas

`backend/app/engine/hybrid_engine.py`:

- **Capa 1** — `rule_engine.collect_findings()`, la barrida heurística completa. Se extrajo de `execute_investigation` precisamente para poder encadenarla sin persistir.
- **Capa 2** — el LLM recibe un **resumen agregado** (hallazgos por tipo, plataformas con presencia, identificadores tras pivotar, herramientas ya ejecutadas y las que no llegaron a ejecutarse) y pide solo lo que falta. No se le manda el volcado de hallazgos: gastaría contexto sin mejorar la decisión de dónde mirar.
- **Persistencia única al final**, con los hallazgos de las dos capas juntos. Si cada capa persistiera por su cuenta, la deduplicación no vería a la otra y un perfil hallado por ambas produciría dos entidades.

**Lo que distingue al híbrido del agente autónomo es el filtro anti-repetición.** `HybridEngine._run_key()` reconstruye la misma clave de ejecución que usó la capa 1 (`RuleEngine._get_tool_run_key`), de modo que una llamada ya cubierta se descarta sin gastar red. Sin ese filtro el híbrido sería el agente corriendo dos veces.

### 3.2 `engine_used`: la métrica que estaba mal

`EvaluationView` clasificaba `strategy == "auto"` como agéntico aunque el orquestador hubiera caído al rule engine por no haber LLM. Corregido en las dos puntas:

- El orquestador anota `engine_used` — el motor que **realmente** corrió — junto a `strategy_used`.
- `metrics.py:engine_of()` agrupa por ese campo y, para los expedientes anteriores a esta fase, lo reconstruye desde `ai_enhanced`, que ya registraba si había LLM en el momento de ejecutar. Sobre las 8 investigaciones existentes, las 8 se reclasificaron a `rules`.
- Una `hybrid` sin LLM **no se acredita al híbrido**: es una corrida de reglas con otro nombre, y así se contabiliza.

`InvestigationCreate.strategy` pasó de `str` libre a `Literal`. Antes una errata (`"hybird"`) devolvía HTTP 201 y caía al motor de reglas en silencio, contaminando la muestra con una condición que nadie pidió; ahora devuelve 422.

### 3.3 Arbitraje por LLM — opcional, apagado y sin contaminar el modelo

`backend/app/identity/arbitration.py`, tras `HYBRID_LLM_ARBITRATION` (por defecto `false`). Somete al LLM los hallazgos de la franja 0.40–0.70 y **nunca sobrescribe `identity_score`**: escribe el veredicto en `metadata_info["llm_arbitration"]` y el resolutor lo lee como *puntuación efectiva* para agrupar. Así el histograma y la curva de calibración siguen midiendo Fellegi-Sunter puro, y el expediente muestra las dos cifras (`0.62 del modelo → 0.72 efectivo`) con la justificación y el modelo que la emitió.

Los veredictos aplican 0.72 / 0.38, justo al otro lado del umbral: el arbitraje decide de qué lado cae un caso fronterizo, no cuánta certeza hay. Fingir un 0.99 sería el mismo atajo que se le quitó al avatar en la Fase 2.

### 3.4 Frontend emparejado

- **Selector de estrategia** con las cuatro opciones, cada una con su explicación, y **aviso previo** si el backend no tiene LLM: la estrategia degradará y quedará registrada como reglas.
- **Consola**: cada evento viaja con `layer` (`heuristic` / `refinement`) y la consola pinta un distintivo `H` / `IA` con su leyenda **solo cuando la investigación tuvo dos capas** — en una corrida heurística marcaría todas las líneas igual y sería ruido.
- **Cabecera del expediente**: motor real, aviso de híbrido degradado, y contador de hallazgos aportados en exclusiva por la IA.
- **Tabla de hallazgos**: distintivo de capa por fila. Un perfil visto por las dos lleva los dos.
- **`EvaluationView`**: las 4 tarjetas de dos cifras se sustituyeron por una tabla métrica × motor de tres columnas (con dos motores ya se leía mal; con tres, imposible), más un panel de **aportación de la capa IA** y la columna `engine_used` en el CSV.
- **`lib/engines.ts`**: fuente única de la presentación de motores y capas, en la línea de `entityTypes.ts` (M1).

### 3.5 Variables de entorno nuevas

```bash
# backend/.env — la capa 2 solo se activa si hay LLM configurado
LLM_MODEL=gemini/gemini-2.0-flash
LLM_API_KEY=...

HYBRID_MAX_REFINEMENT_TURNS=2      # turnos de la capa de refinamiento
HYBRID_LLM_ARBITRATION=false       # arbitraje de la franja ambigua (no determinista)
HYBRID_ARBITRATION_MAX_ENTITIES=12 # tope de hallazgos a arbitrar por investigación
```

### 3.6 Qué queda sin verificar

La capa 2 se probó **en vivo contra un servidor OpenAI-compatible local**
(HTTP real a través de LiteLLM: esquema de funciones, `tool_calls`, secuencia
`assistant`/`tool`), no contra un proveedor de verdad, porque `.env` no tiene
`LLM_MODEL`. Falta una corrida con clave real —Gemini o Groq, ambos con nivel
gratuito— para confirmar que el proveedor respeta el `tools` que se le envía.
Es exactamente el hueco que dejó al descubierto el caso de Tavily.

---

## Fase 4 — Cobertura de fuentes ⬜ PENDIENTE

Cada tool nueva sigue el patrón `BaseTool` + `http_client.build_client()` + registro en `registry.py`. **No hace falta tocar el agente IA:** `_build_agent_tools()` ya genera el schema desde el registry, así que toda tool nueva es automáticamente visible para el LLM.

### 4.1 Adaptador de datasets de username

Nuevo `backend/app/tools/data/dataset_adapter.py` que normaliza **en memoria** dos fuentes que se mantienen en ficheros separados:

| Fuente | Utilizables | Licencia | Aporta |
|---|---|---|---|
| WhatsMyName (ya bundleado) | 716 (hoy se usan 500) | CC BY-SA 4.0 | `uri_check`, `e_code`, `e_string`, `m_string`, `cat` |
| **Maigret `data.json`** (nuevo) | **2960** de 3653 | MIT | `url`/`urlProbe`, `checkType`, `presenseStrs`/`absenceStrs`, **`regexCheck`**, **`alexaRank`**, `tags`, `disabled`, `protection` |

> **El objetivo NO es el volumen, es la precisión.** El valor real de Maigret no son los 3000 sitios sino la calidad de la comprobación: `regexCheck` descarta usernames inválidos **sin gastar una petición**, `absenceStrs` reduce falsos positivos, `alexaRank`/`tags` dan priorización basada en datos en vez del set hardcodeado `PRIORITY_PLATFORMS` (`username_finder.py:34-40`), y `protection: "tls_fingerprint"` identifica los 278 sitios inalcanzables sin `curl_cffi` para saltarlos en vez de quemar reintentos. **Aplicar eso a los sitios que ya se escanean mejora la precisión sin tocar el volumen** — y así es como se defiende en el artículo.

**Antes de subir el cap** hay que resolver el presupuesto de concurrencia: `username_finder` usa `CONCURRENCY_LIMIT = 30` pero el semáforo global de `http_client` es de **40 peticiones para todo el proceso**. Al escalar, el escaneo de usernames **acapara el presupuesto y mata de inanición al resto de tools de la ronda**. Hace falta un presupuesto por tool o por categoría.

### 4.2 Hudson Rock Cavalier — infostealer logs

Nuevo `backend/app/tools/infostealer_checker.py`. Fuente #1 en calidad de OSINT de brechas en 2025-2026, gratuita, sin key, **verificada funcionando**. Complementa `breach_checker.py` (XposedOrNot) sin sustituirlo. Nuevo `entity_type`: `infostealer`.

Devuelve datos cualitativamente distintos y muy potentes para la concientización: fecha de infección, nombre del equipo, sistema operativo, ruta del malware y número de servicios comprometidos. Respetar la minimización que ya practica `breach_checker.py`: **persistir el hecho de la exposición y los servicios afectados, nunca contraseñas**.

**Dos requisitos previos:**
- **Token bucket por host** en `ResilientTransport`. El límite de 50 req/10 s es *por host* y el semáforo global de 40 no lo respeta: la primera demo con varias consultas da 429.
- **Checkbox de "solo sobre mi propia identidad"** en el frontend. Consultar esta API envía a un tercero la identidad de a quién investigas; el checkbox refuerza además el marco pedagógico.

**Frontend emparejado:** tarjeta de alerta dedicada, visualmente más grave que un `breach` normal (es una máquina comprometida, no una filtración de terceros).

### 4.3 Ampliar `email_enumerator`

De los ~20 probes actuales hacia los vectores de `kaifcodec/user-scanner` (MIT, 4.6k estrellas, activo, 175+ vectores de email) — el sucesor de facto de Holehe. Portar por lotes, priorizando plataformas relevantes para estudiantes LatAm.

**Frontend emparejado:** con muchos más resultados, `FindingsTable` necesita **paginación o virtualización**; hoy renderiza todas las filas de golpe.

### 4.4 Dominio personal (crt.sh)

Nuevo `backend/app/tools/domain_finder.py`. Gratis, sin key, verificado. Relevante para el público objetivo: estudiantes de ingeniería con portfolio propio (`juan.dev`). **Frontend:** nueva capa "Infraestructura" en el grafo.

### 4.5 Motor de búsqueda web (prioridad baja)

Sin Brave API, la ruta gratuita es SearXNG auto-hospedado con `format=json`, con el scraping de DuckDuckGo como fallback. Refactorizar `search_dorker.py` a backends pluggables. **Expectativa realista:** desde una sola IP, SearXNG recibe CAPTCHA de Google/Brave/Startpage y en la práctica solo responde DuckDuckGo. La mejora aquí es **arquitectónica**, no de cobertura.

**Frontend emparejado (toda la fase):** badge de fuente/dataset por hallazgo; contador de sitios escaneados vs descartados por `regexCheck`; y **barra de progreso real** del escaneo — el evento `phase: "progress"` de `username_finder` ya se emite y hoy se desperdicia como una línea de log más. Con miles de sitios, una consola muda durante minutos arruina la demo.

---

## Fase 5 — Cosecha activa de avatares ⬜ PENDIENTE

`reverse_image_search.py` existe pero está **apagado**: exige `serpapi_key` o `bing_visual_search_key`, y la restricción es "sin key". Se invierte el planteamiento:

> En lugar de *"busca esta imagen en la web"* (requiere API de pago), hacer *"descarga el avatar de este username en las plataformas donde lo confirmamos y compara los hashes"*.

Nuevo `backend/app/tools/avatar_harvester.py` que construye URLs con patrones directos verificados, tomando como referencia la lista open-source de proveedores de `microlinkhq/unavatar` **sin consumir su API**. Alimenta `context.extra["avatar_urls"]`, que `pivot_rules.py:101-115` **ya recolecta**, y de ahí a `avatar_hasher`. Lo convierte de pasivo a activo.

### Salvaguardas obligatorias (esta fase es la más peligrosa del plan)

- **Solo sobre cuentas ya confirmadas** por `username_finder`, y **6–8 proveedores**, no la lista completa. Construir URLs de avatar para usernames *no confirmados* significa descargar y fingerprintear fotos de terceros que no son el objetivo — precisamente lo que una herramienta de concientización enseña a no hacer.
- **Denylist de avatares por defecto.** dHash 8×8 con umbral Hamming ≤ 6 es permisivo, y los avatares por defecto (mystery-man de Gravatar, siluetas, placeholders monocromos) son **idénticos entre usuarios distintos** → distancia 0 → el resolver hace `confidence = max(confidence, 0.99)` → **dos personas distintas acaban en el cluster "Identidad Principal (Confirmada)"**. Con cosecha pasiva es raro; con cosecha activa sobre la cola larga es la norma, porque la mayoría de esas cuentas no tienen foto.
- Descarte por baja varianza/entropía de imagen; **distancia ≤ 2** para boost automático; y **nunca el override a 0.99**: el avatar debe ser una señal más del Fellegi-Sunter, no un atajo que salta el modelo.

**Frontend emparejado:** mostrar **las miniaturas de avatar** en el grafo y en las tarjetas de cluster, con la distancia de Hamming visible y una arista explícita entre los nodos correlacionados. Hoy la correlación visual ya ocurre y sube la confianza a 0.99, pero **el usuario nunca ve las imágenes ni sabe que pasó**. Es la evidencia más persuasiva del sistema y está oculta.

---

## Qué NO hacer

| Ítem | Veredicto |
|---|---|
| **`phone_enumerator` por flujos de reset** (megadose/ignorant) | **Cortar.** Es el único ítem que **provoca un efecto en la cuenta de un tercero**: dispara SMS/emails de recuperación reales a alguien que no ha consentido. Además activa anti-abuso y bloquea la IP en mitad de la sustentación. No es OSINT pasivo. Para teléfono, quedarse con `phonenumbers` (operador, región, tipo de línea): menos espectacular y defendible |
| **Job de sincronización de datasets cada 24 h** | **Cortar.** Rompe la reproducibilidad (el artículo necesita "N sitios, snapshot Maigret @ `<sha>`"), añade dependencia de red en arranque y es un vector de supply chain: un fichero remoto sin firmar define a qué 3000 hosts mandas tráfico. Snapshot fijado por commit + comando manual |
| **Fusionar WMN + Maigret en un fichero único** | **Cortar.** WhatsMyName es CC BY-SA 4.0 y el ShareAlike se contagia al derivado. Dos ficheros fuente, un adaptador que normaliza en memoria |
| **Vender "4x cobertura"** | **Cambiar el objetivo.** La cola larga de Maigret es de baja calidad y aumenta falsos positivos. Vender precisión (`regexCheck`, `absenceStrs`), no volumen |
| **Lista completa de proveedores estilo unavatar** | Sobredimensionado. 6–8 bastan |
| **`hybrid` como reemplazo del selector de motores** | **Corregir a "tercera estrategia".** Reemplazar mata una feature existente y un brazo experimental del artículo |
| **Arbitraje de clusters por LLM como default** | No determinista en demo. Condición opcional y logueada |
| **Avatar → `confidence = 0.99`** | **Cortar el override.** Señal Fellegi-Sunter, no atajo |
| **Alembic en Fase 1** | Prematuro. Fase 2, con baseline aplanado |
| **Unificar el flujo de control de los motores en Fase 0** | Solo unificar **datos** (persistencia). El control (E) es refactor de comportamiento: cambia coste de LLM, latencia y determinismo. Va en Fase 3, cuando ya haya tests que digan si se rompió algo. **Regla: unifica los datos, no el control** |

---

## Mejoras propuestas más allá del análisis original

| # | Mejora | Por qué |
|---|---|---|
| M1 | **`lib/entityTypes.ts` compartido** | La duplicación divergente de categorías es la causa raíz de los tipos huérfanos; sin esto el bug se repite con cada tipo nuevo |
| M2 | **Barra de progreso real** | El evento `phase: "progress"` ya se emite y se desperdicia |
| M3 | **Miniaturas de avatar en la UI** | La correlación visual ya ocurre y es la evidencia más persuasiva; hoy es invisible |
| M4 | **Panel "¿por qué?" del scorer** | Convierte el score en explicación auditable |
| M5 | **`docs/OSINT_SOURCES.md` vivo** | Materializa la vigilancia continua y documenta licencias (obligatorio para el CC BY-SA de WhatsMyName) |
| M6 | **Tests con `respx` + tiers** | Hoy cero mocks; `test_e2e.py` golpea Internet y tarda ~3 min. Con miles de sitios será inviable |
| M7 | **"Golden investigation"** | Un JSON con `ToolFinding` grabados que se reproduce por `persistence → resolver → clusters`. **Es el único test que detecta si unificar los motores cambió el resultado**, y protege los refactors de las Fases 2 y 3 |
| M8 | **Fixtures de avatares por defecto** | Dos avatares por defecto distintos, verificando que el sistema **no** los correlaciona. Red de seguridad de la Fase 5 |
| M9 | **Accesibilidad y contraste** | Cero atributos ARIA en todo el proyecto; labels sin `htmlFor`; `text-slate-500` sobre `#0b0f17` ≈ 4.3:1 y `text-slate-600` ≈ 2.8:1, ambos bajo AA. 5 usos de `text-[9px]` y 34 de `text-[10px]`, algunos dentro de nodos del grafo que además se escalan con el zoom |
| M10 | **Indicador de ruta activa en el Navbar** | No usa `usePathname()`; los enlaces se ven idénticos estés donde estés. El health check además corre **una sola vez** al montar: si el backend arranca después, la pill sigue roja hasta recargar |

---

## Verificación

**Backend**
```bash
cd backend && uv run pytest -q
```
Línea base: **16 passed** (~3 min). Tras la Fase 0 debe correr **sin Internet** (`-m 'not network'`).

**Frontend**
```bash
cd frontend && npx tsc --noEmit && npx eslint src
```
Línea base: `tsc` limpio; `eslint` con **19 errores preexistentes** (ver
"Correcciones aprendidas"). `npx next lint` ya no existe en Next 16.

**End-to-end por fase**
1. Levantar backend (`uv run uvicorn app.main:app --reload`) y frontend (`pnpm dev`).
2. Lanzar una investigación con un objetivo de huella pública amplia.
3. **Recorrer las 6 pestañas** del expediente y confirmar que **todo hallazgo nuevo aparece con icono, filtro y color propios en las dos vistas, y puntúa en el scorecard** — es el criterio de aceptación de la regla backend↔frontend.
4. Apagar el backend y comprobar que cada pantalla muestra un error honesto, no un vacío ni un dashboard de ceros.
5. Imprimir el informe (Ctrl+P) y confirmar legibilidad sobre papel blanco.

**Fuentes externas**

Antes de cada fase, re-verificar con `curl` que los endpoints gratuitos siguen vivos y anotar el resultado en `docs/OSINT_SOURCES.md`. Se degradan y mueren sin aviso — es la razón de ser del principio de vigilancia continua.
