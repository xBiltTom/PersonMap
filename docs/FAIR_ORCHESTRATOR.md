# PersonMap Lite Orchestrator — Fase 3

Implementado sobre `dac0fdd861e6010b03cb916dc501c22330c7121d`, en
`feat/footprint-lite-fair-demo`. Es adquisición determinista, con un objetivo
operativo aproximado de 3–4 minutos; no es un SLA probado con fuentes reales.
No ejecuta planificación LLM, análisis de posts, Exposure Lens ni reconstrucción.

## Selección explícita y compatibilidad

Crear una investigación con `acquisition_mode: "fair"`. El valor por defecto es
`"normal"`: rules/agentic/hybrid y el workspace externo conservan sus recorridos.
Fair requiere ejecución `internal`; combinarlo con `external` devuelve 422 para
no mezclar el scheduler automático con trabajos manuales concurrentes. El
consentimiento V2 existente sigue siendo obligatorio. La estrategia solicitada
se conserva como dato de entrada, pero Fair siempre registra `engine_used=fair`
y `ai_enhanced=false`, incluso si existe LLM configurado y se pidió hybrid.
Las métricas comparativas muestran Fair por separado.

```json
{
  "acquisition_mode": "fair",
  "execution_mode": "internal",
  "strategy": "rule_based",
  "subject_consent": true,
  "target": {
    "input_version": 2,
    "given_names": "Persona",
    "family_names": "De Prueba",
    "emails": ["persona@example.org"],
    "usernames": [{"username": "persona", "platform": "instagram"}],
    "phones": ["+51912345678"]
  }
}
```

El modo se guarda en `Investigation.metrics.acquisition_mode`; no requiere
migración. `InvestigationRead.acquisition_mode` también lo expone. No hay un
flag global que transforme silenciosamente investigaciones normales.

## Arquitectura y orden efectivo

```text
Orchestrator
  ├─ normal → engines existentes
  └─ fair → FairEngine
               ↓
          FairPlan / SourcePlan
               ↓
          workers de adquisición concurrentes
               ↓ resultados al llegar
          ToolFinding → extractor existente → Pivot Frontier
               ↓ admisión dentro del plan y presupuesto
          nuevos workers, máximo tres generaciones
               ↓
          persist_findings / ToolExecution / EntityObservation
               ↓
          snapshot de descubrimiento + SSE
```

Wave 0 prepara seeds, identificadores tipados y el Frontier existente.
Wave 1 lanza las fuentes aplicables al contexto declarado, por prioridad y hasta
la concurrencia permitida. Apify declarado puede arrancar inmediatamente junto
con búsqueda, brechas y discovery nativo.
Wave 2 consume pivots admitidos de Wave 1. Wave 3 consume los últimos pivots
útiles de Wave 2 y enriquecimientos acotados. La generación se deriva de los
inputs relevantes de cada trabajo, no del número de veces que se llama al scheduler.
No se espera una barrera entre oleadas: un pivot rápido puede alimentar Apify
mientras Maigret u otra fuente de Wave 1 todavía trabaja.

Hay un solo trabajo activo por herramienta para proteger sus caches/contadores.
Herramientas distintas sí trabajan concurrentemente. Breach, Gravatar y
EmailChecker reciben unidades por email; UsernameFinder/GitHub por alias y
phone_lookup por teléfono. Se planifican todos los seeds, dando prioridad a los
declarados. Los límites heredados del especialista pueden dejar inputs sin
consulta: se informa `budget_exhausted`/`partial`, nunca se afirma cobertura total.
No se amplían esos límites para eludir presupuestos.

Las vistas se aíslan por trabajo. Al completarlo solo se fusionan cambios de
runtime y listas acumulativas; una vista antigua no reemplaza contadores de otra
fuente. Apify comparte expresamente su reserva de investigación ya existente.
Cada checkpoint usa una sesión SQL propia. El coordinador permite un solo
checkpoint activo; si su cancelación tarda, no inicia otro sobre esa sesión.
Un timeout de SQL marca persistencia parcial sin retener el snapshot.

## Registry final

`backend/app/engine/fair_plan.py` centraliza prioridades, scopes, timeouts,
clases de coste, fuentes críticas, primer wave, capacidad de producir pivots y
máximo de invocaciones. `GET /api/v1/sources/fair` devuelve el plan efectivo con
`required_inputs` del registry común y no contacta proveedores.

| Fuente | Prioridad | Primera wave | Timeout por trabajo | Scope | Papel |
|---|---:|---:|---:|---|---|
| breach_checker | 0 | 1 | 30 s | email | crítico; exposición, no identidad |
| apify_social | 1 | 1 | 70 s | contexto | crítico para cuentas elegibles |
| Gravatar | 2 | 1 | 20 s | email | crítico |
| phone_lookup | 2 | 1 | 20 s | teléfono | crítico; motor existente |
| SearchDorker | 3 | 1 | 65 s | contexto | crítico; scopes/literal/fallback intactos |
| Academic | 3 | 1 | 75 s | contexto | crítico; OpenAlex/Crossref intactos |
| GHunt | 4 | 1 | 55 s | contexto | crítico cuando aplica; conserva sus cuotas |
| GitHub scanner | 4 | 1 | 45 s | alias | crítico |
| EmailChecker | 5 | 1 | 25 s | email | crítico; incluye asociaciones GitHub existentes |
| UsernameFinder | 5 | 1 | 70 s | alias | crítico; Maigret/WMN, preset fast |
| SocialVerifier | 6 | 1 | 30 s | contexto | crítico si hay candidatos |
| SocialUrlExtractor | 6 | 1 | 8 s | contexto | candidato pasivo, no evidencia de existencia |
| EmailEnumerator | 8 | 1 | 35 s | contexto | opcional, capacidades/cuotas actuales |
| Google público | 9 | 1 | 35 s | contexto | opcional |
| DomainFinder | 10 | 2 | 25 s | contexto | opcional, tras un primer resultado |

Máximo 32 invocaciones para fuentes por input; fuentes de contexto tienen 2–3
invocaciones en el plan. Los máximos no implican que quepan dentro del deadline.
UsernameFinder usa hasta 100 sitios por alias, también limitado por el tope fast
existente. Se desactivan `enrich`, `parse` y retries nativos solo en la vista Fair.
Esto puede recortar el catálogo complementario WMN; no promete revisar todos los
sitios. La ejecución normal mantiene sus opciones anteriores.

Excluidos por defecto de Fair: MaigretEnricher (profundidad adicional), Keybase y
Wikipedia (fuentes secundarias), DNI (fuera de seeds Fair), reverse image
(enriquecimiento secundario) e infostealers (consentimiento separado, fuera del
preset por defecto). Siguen registrados para los workflows normales.

## Tiempo y presupuestos

Defaults:

```env
FAIR_TOTAL_DEADLINE_SECONDS=225
FAIR_FINALIZATION_SECONDS=20
FAIR_CANCELLATION_SECONDS=6
FAIR_CHECKPOINT_SECONDS=5
FAIR_MAX_WAVES=3
FAIR_PARALLELISM=16
FAIR_USERNAME_SITES=100
FAIR_SEARCH_QUERIES=8
FAIR_APIFY_PLATFORMS=["instagram","tiktok","youtube"]
FAIR_DISABLED_SOURCES=[]
```

El presupuesto global usa reloj monotónico desde la entrada al engine Fair.
A los 199 s por defecto cesa la adquisición: quedan hasta 6 s de limpieza y 20 s
reservados para persistencia/snapshot. Cada herramienta tiene además su timeout,
recortado al tiempo de adquisición restante. Las opcionales se cancelan primero,
al 75% de esa ventana (aproximadamente 149.25 s); no se inician nuevos pivots tras
el 90% (aproximadamente 179.1 s). Un plan puede terminar antes si no queda trabajo.
Los parámetros temporales tienen que ser positivos y dejar ventana de adquisición.
La lectura inicial y cada checkpoint reciben también un presupuesto temporal;
una tarea de checkpoint que suprima cancelación se señala como cleanup pendiente.

El coordinador no espera indefinidamente un worker que suprima cancelación:
marca timeout y `cleanup_pending` después de la gracia, y cierra el snapshot.
Los especialistas/productores deben cooperar con cancelación. Python no puede
interrumpir una función que bloquee sin ceder el event loop; para plugins no
cooperativos haría falta aislamiento por proceso. Los workers actuales conservan
sus mecanismos de abort y limpieza. No se afirma que un abort remoto ya haya
terminado solo porque se solicitó. El deadline tampoco garantiza disponibilidad
SQL ni retención si el proceso completo muere.

Frontier recibe límites por llamada Fair, sin modificar settings de modo normal:
6 pivots por wave, 12 acumulados, coste relativo 100, umbral 390 y cero P4 débiles.
Los seeds P0 siempre conservan admisión. P1/P2 y P3 con soporte suficiente pueden
consumir la siguiente oleada. Un descubrimiento de Wave 3 permanece archivado,
pero no abre Wave 4. Solo se consideran herramientas habilitadas en el plan.
Fair mantiene Frontier incluso si el flag del modo normal está desactivado.
No hay un segundo almacén ni ranking de pivots.

## Apify y contenido social

Se llama a la misma BaseTool y se conserva:
`SocialSourceRouter → ApifySocialTool → ApifyClient → ApifyAdapter → ToolFinding`.
Fair intersecta su lista social con `APIFY_PLATFORMS`; nunca expande la allowlist
del operador. Apify continúa requiriendo enabled/token/consentimiento. Para
YouTube hay que incluir también youtube en la allowlist global.

Instagram/TikTok/YouTube son elegibles tempranamente. Threads queda fuera del
plan social por defecto; puede añadirse explícitamente a ambas allowlists, pero
su coste/timeout sigue acotado y no bloquea el resto. Reddit/X/Facebook/LinkedIn
no ganan adapters ni runs por aparecer en esta fase.

- Cuenta declarada con plataforma: runnable desde Wave 1 sin observación nativa.
- Alias sin plataforma o candidato automático: observación nativa plausible,
  Frontier y entonces Apify durante la misma investigación.
- Perfil Instagram sin posts sigue siendo un hallazgo válido.
- Batching, cobertura, builds fijados y límites Actor/run/perfil/contenido/USD
  pertenecen a Fase 2.1. Fair no crea otro ledger ni reintenta POST ambiguos.
- Si un Actor terminó y otro queda pendiente al deadline, Fair conserva los
  ToolFindings del terminado, marca el lote partial y mantiene todas las reservas.
  La opción de preservar resultados al cancelar se activa solo en las vistas Fair.
- Reservas y runtime se guardan en checkpoints y se recargan al reentrar al engine.
  Sigue pendiente la garantía transaccional estricta pre-POST frente a crash duro.

Para Reddit/X/Facebook posteriormente: implementar primero ActorSpec, builder y
adapter productivo; validar esquema/datos/coste; configurar build y allowlists;
reutilizar apify_social y el mismo plan. Para un especialista nativo nuevo,
registrar la BaseTool común y añadir su SourcePlan. No hace falta otra fase de
pivots, otra cola de evidencias ni nuevas condiciones por plataforma en el scheduler.

## Estados, API y SSE

Contrato versionado en `backend/app/schemas/fair.py`. Estados terminales:
`completed`, `partial`, `timeout`, `skipped`, `budget_exhausted`,
`provider_unavailable`, `not_applicable`, `failed`. Durante ejecución se usan
`pending` y `running`. Cada fuente conserva intentos, wave, timestamps, conteo,
referencia opaca al input y reason de diagnóstico; los errores no guardan mensajes
crudos de excepciones ni credenciales.

Se reutiliza EventBus/SSE existente:

- `fair_progress`: phase, elapsed_seconds, deadline_seconds, sources y social_sources.
- `fair_snapshot`: estado final de adquisición.
- `investigation_complete`: incluye mode=fair y partial.
- `fair_unpersisted_findings`: recuperación temporal solo si SQL no pudo guardar
  los últimos ToolFindings. No es almacenamiento duradero ni otro modelo de evidencia.

`GET /api/v1/investigations/{id}/fair` devuelve progress, snapshot y recuperación
pendiente desde el bus local o las métricas persistidas. Detail sigue exponiendo
las entidades normales; trace sigue exponiendo ToolExecution/EntityObservation.
El bus es por proceso: la observabilidad en vivo con varios workers requiere
infraestructura compartida futura. Tras reinicio queda el último checkpoint SQL.

La captura HTTP Fair es task-local y recoge solo códigos/tipos de error para
no etiquetar como completada una fuente que silenció un error HTTP. Fuera de
Fair es una operación vacía. Los diagnósticos propios de GHunt, búsqueda, academia
etc. también se conservan. La cobertura fina depende de lo que cada especialista
publique: un timeout/error nunca se transforma en una prueba de inexistencia.

## Persistencia, snapshot y futura Fase 4

Los hallazgos usan `persist_findings`, deduplicación y provenance existentes.
ToolExecution y EntityObservation se guardan en las tablas actuales, con
engine=fair y engine_layer=fair_acquisition. Checkpoints hasta cada cinco segundos,
cuando se vacía el trabajo y durante cierre. Un fallo hace rollback del checkpoint
actual; los anteriores ya comprometidos sobreviven. Se retienen hallazgos en
memoria y se reintenta al siguiente checkpoint dentro del tiempo restante.
Cada escritura congela su lote, índices, trazas y runtime antes de hacer I/O;
no declara persistidos hallazgos que llegaron mientras la escritura estaba activa.

`metrics.fair_snapshot` contiene:

- declared: seeds originales y su provenance;
- findings: referencias por clave canónica y entity_id cuando se persistió;
- sources: estados e intentos;
- pivots: proyección del Frontier existente;
- social_content, breaches, academic, documents: referencias a las entidades;
- execution: tiempo, deadline, partial, persistencia y cleanup;
- plan: configuración efectiva inspeccionable.

Los cuerpos y evidencias permanecen en Entity.metadata_info; el snapshot no crea
un dataset atribuido ni copia posts a otro almacén. Fase 4 resolverá entity_id y
consultará ownership_review_required para cuentas y provenance para otros
hallazgos. Las cuentas subject_declared no requieren volver a preguntar ownership;
las observaciones de perfil/contenido siguen siendo automatic/discovered.
Las brechas mantienen un hallazgo por email y no son prueba independiente de
identidad. Fair no crea grupos visuales ni análisis semántico al finalizar.

Si todas las escrituras SQL fallan, no puede garantizarse persistencia duradera:
SSE/API del mismo proceso conservan el último estado y hallazgos no guardados;
perder ese proceso pierde esa recuperación. Tampoco se promete exactly-once en
un crash entre POST Apify y commit, ni presupuesto distribuido multi-worker.

## Benchmark y pruebas

```bash
cd backend
.venv/bin/python scripts/benchmark_fair_orchestrator.py \
  --output /tmp/fair-offline.json
.venv/bin/python -m pytest tests/test_fair_orchestrator.py tests/test_apify_social.py \
  tests/test_apify_benchmark.py tests/test_pivot_frontier.py tests/test_hybrid_engine.py -q
.venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
.venv/bin/python -m pytest -q --ignore=tests/test_scan_progress.py --durations=5
```

El benchmark sustituye el registry completo por fuentes sintéticas: 1 s, 5 s,
20 s (supera el deadline) y enriquecimiento simulado de 0.5 s. Usa Frontier y
scheduler reales, ninguna red/token/DB/proveedor. El informe
[audit offline](audits/fair-orchestrator-offline-2026-10-16.json) registra concurrencia,
pivot a Wave 2, cancelación y resultados parciales. Los 6.40 s observados con
ese plan de 7 s son solo del experimento simulado; no demuestran 225 s reales.
No se ejecutaron nuevos Actors de pago para Fase 3.

Las pruebas incluyen inicio concurrente, Apify declarado sin espera, Wave 2 sin
barrera, P4 diferido, tres generaciones máximas, presupuestos Apify reales con
cliente simulado, múltiples emails/aliases, estados HTTP/fallos, deadline y
cancelación resistente, recuperación SQL, API/SSE, dispatch normal/Fair y
persistencia PostgreSQL en esquema temporal. Los resultados de cierre se
registran en FAIR_V2_PLAN.md.


### Cierre de validación (16-10-2026)

- 163 pruebas específicas aprobadas, incluidas 29 Fair, routing/Apify/Frontier e híbrido.
- 19 PostgreSQL/REST/MCP aprobadas; recuperación tras error de escritura y snapshot con IDs reales.
- 1047 regresiones generales aprobadas, 21 excluidas por marcadores, 186.72 s.
  Se omiten los cinco casos lentos sin cambios de `test_scan_progress.py`.
- Benchmark final sin red: 6.4027 s / deadline 7 s, cinco checks aprobados.
- `git diff --check` limpio. No se realizaron nuevos runs Apify pagados.
