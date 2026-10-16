# Base de datos PersonMap Fair/Lite

## Arquitectura

La separación Lite es operacional y usa los modelos y migraciones actuales:

```text
PostgreSQL
├── person_map       → backend normal / legacy actual
└── personmap_lite   → backend Fair/Lite
```

El repositorio configura la base legacy actual como `person_map` (con guion
bajo). No se renombra ni se copia. Un proceso de backend recibe una sola
`DATABASE_URL`; Fair/Lite selecciona `personmap_lite` al arrancarlo. El modo de
adquisición Fair sigue seleccionándose por investigación y no enruta sesiones
entre bases.

`.env.lite.example` contiene una URL local sin contraseña. Ajusta el usuario a
un rol PostgreSQL local con permiso `CREATEDB`; no guardes contraseñas reales en
ese archivo ni en Git.

## Crear `personmap_lite` desde cero

Desde el host, con PostgreSQL local disponible y desde `backend/`:

```bash
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python scripts/bootstrap_personmap_lite.py
```

El script valida que el nombre de base de datos sea exactamente
`personmap_lite`, comprueba conectividad a PostgreSQL, crea la base solo si no
existe, ejecuta `alembic upgrade head` y comprueba el head, tablas críticas,
claves, índices, tipos UUID/JSONB y cascadas del esquema actual. Si la base ya
existe, conserva sus datos y aplica las migraciones pendientes.

## Reset solo para desarrollo

El borrado requiere la opción explícita `--reset` y la misma comprobación estricta
del nombre de base:

```bash
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python scripts/bootstrap_personmap_lite.py --reset
```

El script se niega a resetear `person_map`, otra base o una URL sin base. No hay
un reset para la base legacy.

## Compose

El servicio PostgreSQL existente crea `person_map` en su inicialización. Se
puede crear Lite en el mismo contenedor PostgreSQL y luego arrancar el backend
con el override Fair:

```bash
docker compose up -d postgres
docker compose run --rm --no-deps \
  -e DATABASE_URL='postgresql+asyncpg://person_map:person_map@postgres:5432/personmap_lite' \
  --entrypoint python backend scripts/bootstrap_personmap_lite.py
docker compose -f docker-compose.yml -f docker-compose.lite.yml up -d backend frontend
```

El override solo sustituye el `DATABASE_URL` del proceso backend. Para volver al
backend normal, usa `docker compose -f docker-compose.yml up -d backend frontend`.
Ambos nombres viven en el mismo servidor y volumen de PostgreSQL.

## Migrar y verificar

Desde `backend/`, siempre con la URL de la base que se quiere migrar:

```bash
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/alembic current
.venv/bin/alembic heads
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/alembic upgrade head
```

La revisión base previa a Exposure Lens era `a41b9c2e7d63`; la revisión actual
en Lite es `bf781b42de01`. La migración añade `exposure_runs` y
`exposure_content_cache`. El bootstrap comprueba al menos:
`targets`, `investigations`, `entities`, `relationships`, `tool_executions`,
`entity_observations`, `review_decisions`, `exposure_runs`,
`exposure_content_cache` y `alembic_version`. También valida
UUID, JSONB, índices, unicidad, FKs con `ON DELETE CASCADE` y el CHECK de las
decisiones.

## Arrancar el backend Fair/Lite local

Después del bootstrap, desde `backend/`:

```bash
PERSONMAP_ENV=lite \
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/uvicorn app.main:app --reload
```

El arranque falla si `PERSONMAP_ENV=lite` y la URL señala otra base. Fair Mode
sigue siendo una opción por investigación; este proceso entero usa Lite.

La prueba `test_review_decision_check_unique_valid_values_and_direct_sql_rejection`
inserta `maybe` con IDs válidos mediante SQL directo y verifica que PostgreSQL
lo rechaza por la restricción.

## Smoke test Fair → Verification Gate → dataset

Con Lite ya migrada, desde `backend/`:

```bash
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python scripts/smoke_personmap_lite.py
```

El script usa identidades sintéticas y herramientas fixture, no proveedores
externos. Crea Target, investigación Fair, Entities, ToolExecution,
EntityObservations y tres ReviewDecisions; excluye la semilla declarada de la
revisión; confirma, rechaza y marca dudosa una cuenta; finaliza y consulta el
dataset; después elimina el Target sintético y sus dependencias.

## Prueba PostgreSQL de migración vacía y restricciones

La suite de Verification Gate crea un esquema PostgreSQL nuevo por prueba y
ejecuta todas las migraciones desde cero antes de usar el REST API. Para probar
también la base dedicada real, se puede usar un servidor temporal y luego correr
el bootstrap y el smoke test de arriba. Los tests PostgreSQL incluyen inserts
SQL directos inválidos, unicidad, valores válidos y cascadas.

```bash
cd backend
VERIFICATION_GATE_TEST_DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python -m pytest -m db tests/test_verification_gate.py -q
```

Ese archivo crea y borra esquemas temporales dentro de la base indicada. Usa
Lite o una base descartable; nunca apuntes esta variable a datos que deban
permanecer intactos.

## Pruebas y smoke de Exposure Lens

Los tests de Exposure Lens migran un esquema temporal dentro de Lite, confirman
que `current_database()` es exactamente `personmap_lite` y lo eliminan al
terminar:

```bash
cd backend
PERSONMAP_ENV=lite \
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
EXPOSURE_LENS_TEST_DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python -m pytest tests/test_exposure_lens.py -m db -q
```

El smoke toca Lite directamente solo para insertar el fixture sintético y
elimina target, investigación, decisiones, reporte y cache de contenido:

```bash
cd backend
PERSONMAP_ENV=lite \
DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/personmap_lite' \
  .venv/bin/python scripts/smoke_exposure_lens.py
```

## Evitar una base equivocada

- Antes de arrancar Fair/Lite, revisa que la URL termine en `/personmap_lite`.
- El bootstrap rechaza cualquier nombre distinto, también bajo `--reset`.
- El backend no hace routing dinámico; cada proceso conserva una URL única.
- `PERSONMAP_ENV=lite` etiqueta el arranque de Compose y el bootstrap exige el
  mismo valor si está presente.
- No ejecutes `alembic upgrade head` con la URL legacy cuando quieras preparar
  Lite. La configuración de Alembic obtiene la URL de `DATABASE_URL`.
- No existe una copia automática de investigaciones legacy a Lite.

## Deuda antes de Fase 6

Exposure Lens lee el dataset versionado solo después de
`review_status=complete`. El proceso no autentica todavía al sujeto ni aplica
permisos por investigación; antes de alojar expedientes multiusuario se necesita
autorización. Las fuentes parciales siguen siendo huecos de cobertura, nunca
evidencia de ausencia.
