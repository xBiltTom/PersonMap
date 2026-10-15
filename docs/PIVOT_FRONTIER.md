# Evidence-Aware Pivot Frontier

## Auditoría previa (base `3f054bf`)

`extract_and_apply_pivots()` incorpora correos, alias, teléfonos, URLs de
perfil, avatares, nombres de registros DNI, URLs documentales DNI, webs
declaradas e identificadores tipados (ORCID, GAIA, Steam, etc.). Aplica sus
validaciones existentes y actualiza `TargetContext` y `extra`. Algunas
herramientas también añaden identificadores directamente durante su ejecución.

`RuleEngine.collect_findings()` comparte ese contexto entre herramientas
concurrentes, reúne sus resultados y aplica la extracción al acabar cada ronda.
Hace hasta cuatro rondas. `run_key` contiene el conjunto de inputs requerido
por cada herramienta y, en casos específicos, configuración/cobertura. Impide
repetir una combinación completa, pero no garantiza por sí solo que un email
antiguo no se consulte otra vez cuando crece el conjunto. La cobertura propia
de username, búsqueda, GHunt, correo, GitHub y académico evita parte de esas
repeticiones. No hay ranking global de inputs.

Los límites son heterogéneos: tres alias por investigación, tres teléfonos,
presupuestos de consultas web, límites de correo, identificadores, URLs,
peticiones académicas, tiempo y concurrencia HTTP. No se deben interpretar
como un presupuesto homogéneo de pistas. El híbrido ejecuta primero reglas y
después hasta dos turnos LLM; comparte claves, contexto y persistencia final.

`identity.evidence.signals()` ya distingue contactos declarados, correos de
commit, menciones y consultas exactas. Su peso visual y los grupos del resolver
no son probabilidades de identidad. La Frontier reutiliza roles, no pesos ni
grupos. `trace_recorder` guarda rondas, ejecuciones y observaciones enlazadas
tras deduplicar. `durable_runtime()` permite añadir estado JSON sin migración.

Cobertura previa relevante: `test_hybrid_engine`, `test_trace`,
`test_phone_engine`, `test_social_engine`, `test_maigret_capabilities`,
`test_search_coverage`, `test_correlation_evidence`, `test_workspace_updates`,
`test_agent_fallback` y pruebas de cada herramienta. La integración real
`test_e2e` requiere PostgreSQL y red y se excluye por defecto.

## Decisión de integración

Se conserva la extracción. Una capa adicional registra sus resultados y
admite un subconjunto ordenado de inputs por ronda. El contexto canónico
conserva todas las pistas; una vista de ejecución contiene las admitidas.
Las herramientas mantienen su concurrencia, presupuestos y `run_key`.
Los cambios de runtime y pistas añadidas directamente por herramientas vuelven
al contexto canónico sin sobrescribir las pistas aplazadas.

El estado `explored` significa que al menos una herramienta compatible terminó
una ejecución que recibió ese input. No asegura agotar sus fuentes ni demostrar
una identidad. Se conservan herramientas receptoras y rondas de selección.
Las pistas sin herramienta actualmente ejecutable permanecen disponibles.

Las URLs retienen sus canales de entrada (`candidate_urls`,
`personal_domain_urls`, `dni_source_urls`). Es necesario porque `dni_lookup`
declara solo `dni`, pero consume documentos descubiertos en `dni_source_urls`.
Se prueba el recorrido DNI → documento → nombre → búsqueda con el test previo.
Si no existe seed de un tipo, la vista presenta el primer descubierto admitido
en su campo principal para las herramientas que usan `BaseTool.can_run()`.
Esto no modifica el seed del contexto canónico.

## Evidencia y prioridad

`PivotCandidate` tiene clave estable por tipo/valor normalizado, soportes
referenciados, clases P0–P4, puntuación descompuesta, herramientas posibles,
coste, estado y rondas. Respeta IDs sensibles a mayúsculas y las claves de
recursos URL existentes. No duplica entidades ni cuerpos de observaciones.

| Clase | Criterio | Base |
|---|---|---:|
| P0 | Input del usuario | 1000, fijo |
| P1 | Contacto/identificador publicado, perfil observado, enlace o web declarados | 800 |
| P2 | Evidencia contextual de al menos dos familias independientes | 600 |
| P3 | Mención documental/contextual | 400 |
| P4 | Snippet, candidato sin asociación o sugerencia LLM | 200 |

Una pista P1 corroborada sigue siendo P1 y recibe el bono; no se degrada a P2.
Los roles se obtienen de `identity.evidence.signals()` y de campos de extracción
existentes. Una validación de formato o un eco del correo consultado no se
convierten en publicación declarada. Las sugerencias LLM son P4; sus argumentos
no pueden proporcionar roles, soportes ni clases de evidencia.

Para P1–P4:

```text
pivot_priority = base
  + min(3, max(0, independent_source_count - 1)) * corroboration_bonus
  + 5 si hay evidencia fuerte
  + information_gain
  - exploration_cost
  - min(10, número de herramientas receptoras anteriores)
  - 10 si es P4
```

El bono configurable vale 30 por defecto. Ganancia: email/ORCID 12, username
10, URL/teléfono/DNI 8, nombre/otros IDs 6 y avatar 2. `high/medium/low`
representan potencial de exploración, sin estimación probabilística.

El coste es el máximo de las herramientas posibles, en unidades relativas:
username 20, enriquecimiento Maigret 12, GHunt/enumeración de email 10,
búsqueda/academia/imagen 6, dominio 4, GitHub 3 y lookup sencillo 1. La suma
sirve para admitir pistas, no para prometer cuántas peticiones se harán ni su
precio. Las bases separan clases incluso con los bonos configurables máximos.

El soporte se deduplica por fuente/herramienta/recurso/rol/pista. Cambiar un
adaptador no crea una fuente independiente: se agrupan hosts de servicio del
mismo proveedor, se respeta `original_source_url`/`parent_source_url` y un DOI
compartido conserva el mismo origen. Los ecos de lookup no cuentan como
confirmaciones independientes. Los soportes conservan referencia a ejecución
cuando existe traza DB, y a observación si ya venía suministrada. No se inventan
IDs de filas de observación; `observation_key` es una clave de deduplicación.

## Presupuestos y modos

Configuración compatible con `.env`:

| Variable | Default | Alcance |
|---|---:|---|
| `PIVOT_FRONTIER_ENABLED` | `true` | `false` usa el flujo acumulativo anterior |
| `PIVOT_MAX_PER_ROUND` | 12 | Nuevas admisiones, además de seeds |
| `PIVOT_MAX_TOTAL` | 128 | Pistas distintas admitidas, además de seeds |
| `PIVOT_MAX_WEAK_PER_ROUND` | 2 | P4 en standard |
| `PIVOT_MIN_PRIORITY` | 0 | Umbral standard, sin descartar registros |
| `PIVOT_ROUND_COST_BUDGET` | 100 | Coste estimado de nuevas admisiones |
| `PIVOT_DEEP_MAX_ROUNDS` | 8 | Rondas de reglas en deep |
| `PIVOT_CORROBORATION_BONUS` | 30 | Bono por familia independiente adicional |

`POST /api/v1/investigations` admite `pivot_mode: "standard" | "deep"`.
Standard mantiene cuatro rondas. Deep permite P4 sin cuota específica ni
umbral mínimo, manteniendo los límites generales de cantidad/coste y los de
cada herramienta. Es independiente de `username_scan_mode` y del catálogo.
Seeds tienen prioridad y admisión máximas; tampoco eluden límites de servicios.

El híbrido recibe hasta cinco pistas por nivel en un resumen compacto. Sus
llamadas pasan por la misma admisión; una pista aplazada no entra por argumento
explícito. Varias llamadas en un turno comparten presupuesto de admisión.
Inputs válidos propuestos por el LLM se conservan como P4 y pueden explorarse
en deep. Los cambios de runtime vuelven al contexto canónico y se registra qué
herramienta completó la ejecución receptora. Las claves anti-repetición previas
se conservan tanto en reglas como en refinamiento.

## Persistencia, trazas y contrato

`collection_runtime.pivot_frontier` y `external_runtime.pivot_frontier` usan
el JSON existente. La configuración entra en la huella de investigación.
`trace_recorder.record_event()` registra decisiones por ronda/turno y sus IDs;
el evento SSE contiene además clases, prioridades y motivos seleccionados.
No se crea otro almacén de trazas ni una migración.

`GET /api/v1/investigations/{id}/frontier` devuelve un contrato Pydantic:

```json
{
  "pivot_frontier": {
    "version": 1,
    "semantics": "investigation_priority_not_identity_probability",
    "pending": [], "active": [], "explored": [], "deferred": [],
    "summary": {"total": 0, "high": 0, "medium": 0, "low": 0},
    "decisions": [], "duplicate_executions_avoided": 0
  }
}
```

Cada array contiene candidatos con soportes, razones y componentes del score.
El endpoint de contexto del workspace también expone `pivot_frontier`. La
lectura del snapshot almacenado no recalcula puntuaciones con otra configuración.
Una investigación antigua sin Frontier devuelve arrays vacíos.
El endpoint lee el snapshot persistido al cierre del motor; las decisiones
en vivo viajan por SSE. No se añade un checkpoint duradero por cada request.

## Benchmark reproducible

Desde `backend`:

```bash
.venv/bin/python scripts/benchmark_pivot_frontier.py --baseline-ref 3f054bf \
  --output ../docs/experiments/2026-10-15-pivot-frontier-benchmark.json
```

Se carga el RuleEngine real de `3f054bf` mediante `git show`, con Frontier
desactivada, y se compara con el actual. Usa el fixture previo
`identity_ground_truth.json` (caso `email_declarado`), conserva solo el username
como seed y añade un email contextual de docente y otro débil en un snippet.
Se explicita `profile_email` y el estado de perfil observado para representar
publicación directa; no se usan las etiquetas de identidad del fixture.

Una herramienta de descubrimiento devuelve las observaciones en orden débil,
contextual, fuerte. Un lookup usa `httpx.MockTransport` y el mismo presupuesto
global de dos requests en ambas condiciones. Los contadores de exploración
cuentan inputs consumidos por el fixture, no todos los inputs despachados.
Se incluyen el seed y las URLs conservadas; "deferred" en BEFORE significa
conservado sin consulta, porque ese motor no tenía ese estado explícito.

| Métrica | BEFORE | AFTER |
|---|---:|---:|
| Ejecuciones | 2 | 2 |
| Requests simuladas | 2 | 2 |
| Pistas únicas descubiertas, sin seed | 5 | 5 |
| Pistas exploradas, con seed | 3 | 3 |
| Pistas conservadas sin consultar | 3 | 3 |
| Resultados del contacto fuerte | 0 | 1 |
| Resultados del contacto débil | 1 | 0 |
| Resultados del contacto contextual | 1 | 1 |
| Repeticiones evitadas instrumentadas | no medido | 2 |

Antes se consultan `unrelated@example.org` y `professor@university.example`;
después, `cmendoza@untumbes.edu.pe` y el docente. El email débil se conserva.
El [JSON medido](experiments/2026-10-15-pivot-frontier-benchmark.json) incluye
tres tiempos alternos, mediana, SHA-256 del código base y notas de alcance.
La Frontier añade trabajo local: no se afirma una mejora de latencia ni de
recall en producción. Este fixture demuestra orden y conservación bajo el
mismo presupuesto, no una evaluación amplia de herramientas OSINT.

## Límites conocidos

- `explored` significa input ofrecido a una herramienta que terminó; no asegura
  una request por pista. Límites internos pueden truncar un batch. Para medir
  cobertura real se deben consultar también las coberturas de cada herramienta.
- Deep es finito y no elude cuotas, consentimiento ni rate limits. Pistas
  débiles pueden quedar aplazadas al agotar tiempo, rondas o presupuesto.
- La independencia usa familias de origen conservadoras. No detecta toda
  sindicación ni reconstruye una genealogía de datos si falta procedencia.
- Las puntuaciones ordenan investigación; no indican propiedad de cuentas ni
  pertenencia al objetivo. No se cambian resolver, proyección ni correlación.
- El agente autónomo conserva su planificador; comparte la extracción y el
  registro de pistas, pero no se sustituye su programación por la Frontier.
- No hay migración, UI nueva ni fuentes OSINT nuevas. No se mide aquí el flujo
  real PostgreSQL → fuentes externas, que requiere entorno y pruebas `db/network`.

## Archivos del cambio

| Archivo | Propósito |
|---|---|
| `backend/app/engine/pivot_frontier.py` | Modelos, soportes, scoring, coste, ranking, estados y vistas |
| `backend/app/engine/pivot_rules.py` | Hook aditivo tras la extracción existente |
| `backend/app/engine/rule_engine.py` | Admisión por ronda, concurrencia original y traza |
| `backend/app/engine/hybrid_engine.py` | Digest compacto, sugerencias P4 y presupuesto por turno |
| `backend/app/core/config.py` | Budgets validados |
| `.env.example` | Variables y defaults documentados |
| `backend/app/core/runtime.py` | Serialización en el runtime existente |
| `backend/app/core/fingerprint.py` | Huella de configuración Frontier |
| `backend/app/schemas/investigation.py` | Modo standard/deep por investigación |
| `backend/app/api/v1/investigations.py` | Endpoint con contrato Pydantic |
| `backend/app/services/workspace.py` | Conservación del modo, restauración del runtime y exposición |
| `backend/tests/test_pivot_frontier.py` | Pruebas semánticas y de integración |
| `backend/tests/fixtures/pivot_frontier_scenario.json` | Escenario controlado derivado del fixture previo |
| `backend/scripts/benchmark_pivot_frontier.py` | Comparación con el motor base real del historial Git |
| `docs/experiments/2026-10-15-pivot-frontier-benchmark.json` | Resultados medidos y referencias de código |
| `docs/experiments/2026-10-15-pivot-frontier-validation.json` | Resultados exactos de validación y exclusiones |
| `docs/PIVOT_FRONTIER.md` | Auditoría, arquitectura, scoring, contrato y limitaciones |

## Validación

| Comprobación | Resultado |
|---|---|
| Suite backend previa | 862 passed, 16 deselected; 560.65 s |
| Suite backend con Frontier | 887 passed, 16 deselected; 606.52 s |
| Suite anterior con Frontier desactivada | 862 passed, 16 deselected; 576.38 s |
| Reglas, híbrido, Frontier, DNI, trazas y workspace tras revisión final | 97 passed; 15.20 s |
| OpenAPI | Modelo de respuesta Frontier y campo `pivot_mode` comprobados |
| TypeScript | No ejecutado: no se modificaron archivos frontend TS/TSX |

Hay 25 casos nuevos de Frontier. Cubren seeds, roles, corroboración, duplicados,
orígenes derivados, eco de lookup, contaminación documental, conservación de
débiles, deep, presupuestos, repetición, errores, persistencia JSON, API,
mayúsculas de IDs, trazabilidad y restricciones de sugerencias LLM.

La primera suite con Frontier detectó una regresión del flujo DNI (1 failed,
885 passed): faltaba declarar el consumo de `dni_source_urls` por `dni_lookup`.
Se corrigió y las repeticiones enfocada y completa pasaron. Los guards finales
de normalización y la compatibilidad de runtime desactivado se comprobaron de
nuevo con las 97 pruebas enfocadas. Los resultados exactos y comandos están
en [el registro de validación](experiments/2026-10-15-pivot-frontier-validation.json).
No se ejecutaron las 16 pruebas marcadas `network`/`db`.
