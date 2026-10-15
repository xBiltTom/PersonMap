# Enumeración de correo y técnicas de Holehe

`email_enumerator` conserva el contrato del registry, reglas, agente, híbrido y
MCP. Integra **25 comprobaciones**: 22 adaptadas de consultas/validaciones de
Holehe y tres propias (Chess.com, Adobe y Steam). El paquete/CLI de Holehe no
se instala: se conservan asyncio, HTTPX y los límites HTTP compartidos de Person
Map. GHunt mantiene su entorno, sesión y consultas Google independientes.

## Procedencia y mantenimiento

El último commit observado en la rama `master` de
[megadose/holehe](https://github.com/megadose/holehe/commits/master/) es
`14da70f588538936b20d238783c5e28a0772a2b3`, del **10 de septiembre de 2024**.
Esto describe la rama oficial; no afirma que sus forks o servicios comerciales
tengan la misma fecha, ni que todos sus módulos estén inoperativos.

[Procedencia y hashes de los módulos](vendor/holehe/provenance.json),
[atribución](vendor/holehe/NOTICE.md) y [licencia original GPL-3.0](vendor/holehe/LICENSE.md).
El código adaptado se mantiene en `app/tools/email_catalog.py`; no se ejecutan
archivos descargados dinámicamente ni módulos desconocidos del repositorio.

Se adoptaron consultas de Spotify, X, GitHub, Duolingo, Firefox, LastPass,
Strava, WordPress, Replit, Any.do, Pinterest, Patreon, Plurk, Deliveroo, Issuu,
amoCRM, Diigo, Last.fm, Eventbrite, CodePen, Codecademy y Envato. Que haya un
adaptador implementado **no garantiza que su endpoint siga accesible**.

No se ejecutan las altas completas de Discord/Tumblr, flujos que envían
recuperaciones, comprobaciones que requieren tokens estáticos del proyecto
original ni duplicados de Google/Gravatar. Strava usa la consulta `email_unique`,
en lugar del antiguo POST a `athletes`. GitHub recupera el token del control de
correo; no usa el de usuario ni trata cualquier HTTP 422 como registro. Steam
`84` se clasifica como límite de peticiones, nunca como cuenta detectada.

## Resultados y límites

Cada par correo/servicio guarda estado, número de peticiones y último código
HTTP. Los estados incluyen `registered`, `not_registered`, `non_discriminating`,
`blocked`, `rate_limited`, `unavailable`, `redirected`, `csrf_unavailable`,
`unexpected_response`, `upstream_error`, `transport_error`, `timeout` y
`budget_exhausted`. No se guardan cookies, tokens, mensajes de excepción ni
respuestas crudas.

Solo una señal explícita crea `email_registration`. Se consulta un correo
aleatorio del mismo dominio como control: si también aparece registrado se
descarta el hallazgo. Si el control falla, la señal conserva
`negative_control=untested` con menor confianza. Un control no registrado
permite `negative_control=passed`; ninguno confirma por sí solo el dueño.

El hallazgo conserva la portada como `service_url`, no como URL de un perfil.
No se inventan alias a partir del correo ni se alimenta Maigret con una cuenta
que no se haya identificado. La existencia de un perfil y su asociación con
la persona requieren otras observaciones.

La cobertura se guarda por investigación: las rondas y pivotes no repiten los
correos ya comprobados; los nuevos correos respetan el presupuesto total.
Cambiar catálogo/configuración invalida solo esta cobertura. MCP admite `force`
para repetir y conserva la cobertura de GHunt/Maigret. Cancelar o agotar el lote
cierra las tareas pendientes y preserva los hallazgos ya terminados.

| Variable | Predeterminado | Alcance |
| --- | --- | --- |
| `EMAIL_ENUM_SITES` | `[]` | Vacío selecciona el catálogo; una lista selecciona IDs concretos |
| `EMAIL_ENUM_MAX_EMAILS` | `3` | Correos por investigación |
| `EMAIL_ENUM_CONCURRENCY` | `6` | Comparte los límites globales y por host |
| `EMAIL_ENUM_REQUEST_TIMEOUT` | `7` | Segundos por petición, sin reintentos automáticos |
| `EMAIL_ENUM_PROBE_TIMEOUT` | `20` | Segundos por servicio, incluido control y CSRF |
| `EMAIL_ENUM_BATCH_TIMEOUT` | `90` | Segundos por ejecución; conserva resultados terminados |

REST: `GET /api/v1/email-enumerator/capabilities`.
MCP: `get_email_enumerator_capabilities` y `email_enumerator`. El contexto MCP
incluye diagnósticos; las ejecuciones y la consola guardan los conteos de
estados, incluso cuando no hay hallazgos. No requiere migración de BD.

## Verificación

Las pruebas HTTP simuladas cubren las 25 sondas, ambos valores explícitos cuando
el protocolo los define, schemas inesperados, respuestas genéricas, servicios
que aceptan cualquier correo, CSRF, límites, cancelación, continuidad del motor
y ausencia de pivotes inventados. Las pruebas PostgreSQL usan un esquema
temporal y comprueban la persistencia por MCP, deduplicación y repetición.

```bash
cd backend
.venv/bin/pytest tests/test_email_enumerator.py tests/test_negative_controls.py tests/test_common_social_regressions.py -q
.venv/bin/pytest tests/test_mcp_workspace_db.py -m db -q
.venv/bin/python scripts/email_enumerator_audit.py --output /tmp/email-audit.json
```

La auditoría usa por defecto una dirección aleatoria y publica solo estados.
`--sites spotify,wordpress,lastfm` selecciona servicios. `--operator-email`
solicita un correo propio mediante entrada oculta; no lo incluye en el informe.
La auditoría de control solo verifica respuestas para esa dirección: no prueba
por sí sola la detección de registros existentes ni la cobertura de todo Holehe.

La prueba en vivo del **2026-10-14 (Lima)** con el primer catálogo produjo diez
negativos explícitos y cero hallazgos; el resto fueron bloqueos o consultas
incompatibles. Se observó además el nuevo campo `isEmailAvailable` de Chess.com
y se añadió su interpretación estricta, conservando el formato anterior.

La [repetición con el parser actualizado](experiments/2026-10-14-email-enumerator-live.json)
completó 27 peticiones: **11 negativos explícitos, cero hallazgos** y 14
servicios con bloqueo, error o respuesta incompatible. Esto no verifica la
detección positiva de cuentas reales ni garantiza operativos los 25 servicios.
La suite general pasó 742 pruebas; nueve pruebas PostgreSQL también pasaron.
Las regresiones posteriores del formato de Chess.com se comprobaron aparte.
