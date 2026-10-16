# Verification Gate — Fase 4

El Verification Gate convierte los descubrimientos de una investigación Fair en
una proyección atribuible que pueden consumir fases posteriores. Conserva la
evidencia original en `entities`, observaciones, ejecuciones y relaciones; la
revisión solo agrega una decisión humana.

## Qué se revisa

La API agrupa la revisión alrededor de identidades que pueden atribuirse:

- cuentas sociales y perfiles públicos nuevos;
- emails y teléfonos nuevos;
- perfiles académicos principales (por ejemplo, autor OpenAlex);
- registros de cuenta asociados a un identificador cuando constituyen una
  identidad pública revisable.

Posts, bios, documentos sueltos, menciones de búsqueda y brechas no generan una
tarjeta individual. El contenido depende de la cuenta; publicaciones académicas
dependen de un perfil y de una relación de autoría comprobada por el motor.

## Declarado y descubierto

`Target.extra_data.footprint_input.declared_seeds` es la fuente de datos que el
sujeto dio al inicio. La pantalla los muestra en solo lectura como «Confirmado
por ti al inicio» y nunca crea candidatos para ellos.

Una cuenta solo es declarada si coinciden el alias **y la plataforma**. Un
Instagram declarado no declara un TikTok con el mismo alias. Alias, nombre,
dominio de email, existencia de cuenta y puntuación de correlación no prueban
pertenencia.

Los perfiles descubiertos conservan `origin=automatic`. Una decisión cambia el
estado de ownership, no quién observó originalmente la entidad. La proyección de
una observación declarada también conserva origen automático si la herramienta
la obtuvo; la declaración queda representada por la semilla y el ownership.

## Decisiones y persistencia

`PATCH /api/v1/investigations/{id}/review/{candidate_id}` recibe únicamente:

```json
{"decision":"confirmed"}
```

Los valores admitidos son `confirmed`, `rejected` y `uncertain`. El servidor
busca la entidad por ID dentro de esa investigación y comprueba que siga siendo
revisable. Campos adicionales, metadata y estados enviados por una herramienta
no se aceptan. Repetir la misma decisión es idempotente; un cambio actualiza la
decisión activa y añade una entrada a `review_decisions.history`.

`review_decisions` contiene solo `investigation_id`, `entity_id`, decisión,
fecha e historial breve. No duplica entidades ni evidencias. La metadata de una
cuenta refleja la decisión para lectores del expediente, con
`ownership_review_required=false`; el registro de decisiones es la auditoría
canónica. Una escritura posterior de una herramienta enriquece los metadatos,
pero preserva el estado humano activo.

Estados de `DataProvenance`:

| Caso | `origin` | `status` | Atribuido |
|---|---|---|---|
| Semilla declarada | `subject` | `declared` | Sí |
| Hallazgo nuevo | `automatic` | `discovered` | No |
| Confirmado por el sujeto | `automatic` | `confirmed` | Sí |
| Rechazado por el sujeto | `automatic` | `rejected` | No |
| Dudoso | `automatic` | `uncertain` | No |

Rechazados y dudosos permanecen en el almacén bruto. No hay propagación a otras
cuentas por alias compartido.

## Herencia de observaciones dependientes

Al confirmar una cuenta, el dataset incluye su perfil y los elementos de
`metadata_info.public_content` ya observados. Las publicaciones mantienen
`origin=automatic` y referencian `account_entity_id`; no se pregunta por cada
post. Una cuenta declarada tiene el mismo tratamiento de contenido dependiente.
El dataset no ejecuta análisis de posts ni clasificación de exposición.

Cada cuenta mantiene `entity_id`, plataforma, username, URL pública, bio,
avatar, `collection_sources`, `provenance`, ownership, herramientas fuente y
evidencia. La proyección omite tokens, cabeceras, reservas de costos y metadatos
internos de ejecución.

## Brechas

Una observación de breach no es una identidad ni una prueba de titularidad. Se
incorpora cuando su email coincide exactamente con un correo declarado o
confirmado, con el email asociado y el campo
`exposure_observed_not_identity_proof`. Un breach sobre un email nuevo pendiente,
rechazado o dudoso queda fuera del dataset atribuido y permanece en bruto.

## Perfiles académicos

Se revisa el perfil académico principal. Las publicaciones solo heredan inclusión
si existe una arista `authored_work` del motor académico para ese perfil
confirmado. El dataset identifica la fuente de verificación y el perfil padre.
No crea identidades para coautores. No altera los contratos de OpenAlex/Crossref,
su evidencia de autoría ni sus criterios de coincidencia.

## Adquisición parcial y finalización

El endpoint de revisión devuelve el estado de fuentes Fair y conserva estados
como `partial`, `timeout` y `provider_unavailable`. Se puede revisar cualquier
resultado disponible aunque alguna fuente haya fallado. La pantalla aclara que
una búsqueda parcial no permite concluir que no haya más datos públicos.

`POST /api/v1/investigations/{id}/review/finalize` requiere que Fair haya
terminado y tenga un snapshot persistido. Exige que no haya candidatos
`pending`; si quedan, responde 409 con el código estable
`review_has_pending_candidates` y el número pendiente. El sujeto debe confirmar,
rechazar o marcar cada candidato como `uncertain`. `uncertain` es una decisión
completa que mantiene el hallazgo fuera del conjunto atribuible. El botón se
deshabilita mientras haya pendientes y muestra cuántos quedan. Cambiar una
decisión la reabre. Si aparece un candidato nuevo tras finalizar, sus decisiones
previas se conservan, la revisión se presenta como `in_progress` y el endpoint
del dataset exige finalizar de nuevo.

PostgreSQL impone también el CHECK `ck_review_decisions_valid_decision` para
`confirmed`, `rejected` y `uncertain`. La migración `a41b9c2e7d63` lo añade sin
reescribir la migración histórica de la tabla.

## Dataset estable y contrato con Fase 5

`GET /api/v1/investigations/{id}/reviewed-footprint` responde 409 hasta finalizar.
La versión 1 se persiste en `investigations.metrics.reviewed_footprint_dataset`;
las decisiones permanecen en su tabla normalizada.

```json
{
  "version": 1,
  "subject": {"declared": []},
  "accounts": [],
  "emails": [],
  "phones": [],
  "academic_profiles": [],
  "documents": [],
  "breaches": [],
  "social_content": [],
  "review": {"confirmed": [], "rejected": [], "uncertain": []},
  "evidence": [],
  "execution": {
    "source_investigation_id": "...",
    "reviewed_at": "...",
    "source_mode": "fair",
    "acquisition_partial": false,
    "attribution_policy": "declared_and_human_confirmed_only"
  }
}
```

Fase 5 puede iterar las cuentas declaradas/confirmadas y leer su contenido
público, siempre que mantenga IDs, plataforma, URL, procedencia, ownership,
fuentes de colección y evidencia. `rejected`, `uncertain`, pendientes, pivots y
correlaciones no entran por defecto. Las decisiones no se muestran como
porcentajes de probabilidad.

## Límites de autorización

Las transiciones son operaciones explícitas de servidor y no pueden ser creadas
por las herramientas. La aplicación todavía no autentica personas ni aplica
permisos por investigación; `source=verification_gate` acredita la ruta que
escribió la decisión, no una identidad verificada. Debe añadirse autorización
antes de alojar expedientes de varios usuarios.

## Validación

La integración REST/PostgreSQL está en `backend/tests/test_verification_gate.py`
y requiere una base de datos descartable indicada por
`VERIFICATION_GATE_TEST_DATABASE_URL`; sin esa variable, pytest la marca como
omitida. Los tests de estado y contrato del cliente se ejecutan con
`cd frontend && node --experimental-strip-types --test tests/reviewState.test.mts`.
El bootstrap de una base Lite aislada y su smoke test están en
[FAIR_DATABASE.md](FAIR_DATABASE.md). La suite de PostgreSQL migra un esquema
vacío antes de cada caso y comprueba CHECK, unicidad y cascadas.
