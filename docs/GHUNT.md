# GHunt en Person Map

GHunt **2.3.4** se usa como biblioteca original en un proceso y entorno Python
separados. Su versión y dependencias están fijadas en
`backend/integrations/ghunt/uv.lock`. El backend conserva su propio `uv.lock`:
HTTPX 0.28.1/Pillow 12 y Maigret no se sustituyen por las versiones de GHunt
(HTTPX 0.27.2/Pillow 10.4.0). El runtime aislado usa Python 3.12.

Proyecto original: [mxrch/GHunt](https://github.com/mxrch/GHunt), AGPL-3.0.
Los parsers y APIs son los originales; el adaptador controla transporte,
presupuesto, autenticación local y conversión a observaciones de Person Map.

## Alcance implementado

| Entrada / servicio | Comportamiento |
| --- | --- |
| Correo | Consulta exacta PeoplePa y contenedor `PROFILE`; acepta dominios personalizados, no supone que todo `.edu` use Google |
| GAIA ID | Consulta directa por ID tipado; no se convierte en alias |
| Perfil | GAIA, foto/portada no predeterminada, servicios y tipos expuestos, fecha de actualización; nombres/correos solo si el parser los devuelve |
| Maps | Estadísticas de contribuciones; GHunt 2.3.4 tiene comentada la extracción de reseñas/fotos individuales |
| Calendar | Metadatos y hasta 20 próximos eventos públicos; API/parser nativos con autenticación desactivada y cliente sin cookies |
| Play Games | Hasta tres resultados de búsqueda del parser protobuf nativo; siguen siendo candidatos, no se atribuye el primero al correo |
| Drive/Docs | Metadatos y participantes de un archivo/carpeta explícito con permiso público `anyone`/`anyoneWithLink`; recursos privados se omiten |
| YouTube / Scholar | Siguen en `google_account_osint`, como búsquedas públicas complementarias |

No se implementan BSSID/geolocalización Wi-Fi ni Digital Asset Links: no son
entradas del modelo de investigación de personas. Tampoco se descargan todas
las partidas/logros de jugadores candidatos, se recorren carpetas de Drive o
se extraen comentarios masivamente. Esta integración no promete el 100 % de
los comandos de la CLI.

La existencia de un perfil Google no confirma su dueño. Los resultados llevan
`verification_status=candidate`, `ownership_status=unverified`, procedencia y
contexto de acceso. Los colaboradores de Drive se conservan como participantes
del documento, sin convertir sus correos/GAIA en nuevos identificadores del
objetivo. El perfil Google sí puede aportar un GAIA candidato para Maigret.

## Instalación local

Desde `backend`, con Python 3.12 disponible:

```bash
uv sync --project integrations/ghunt --python 3.12 --frozen
.venv/bin/python scripts/ghunt_session.py status
```

No instalar `ghunt` con pip dentro de `backend/.venv`. La imagen Docker ya
construye ambos entornos por separado; reconstruirla instala el runtime.

## Sesión del operador

No se necesitan credenciales de la persona investigada. Se configura una
sesión de la cuenta del operador mediante
[GHunt Companion](https://github.com/mxrch/ghunt_companion).

Desde `backend`:

```bash
.venv/bin/python scripts/ghunt_session.py login --credentials .ghunt/creds.m
```

El comando pide la autenticación de Companion, un OAuth token o un master
token mediante entrada oculta; nunca pasarlos como argumento, por MCP ni en
una investigación. Guarda la sesión completa con permisos `0600` y no
sobrescribe una sesión existente. `.ghunt/`, `creds.m` y los archivos de avance
`*.ghunt-pending` están excluidos de Git y del contexto de Docker.

Se conservan las cookies entregadas por Companion y se validan con Google.
Las APIs integradas consumen cookies/SAPISID/OAuth; no necesitan los OSID de
Cloud Console/Calendar que GHunt intenta generar por defecto. El adaptador
mantiene la generación y comprobación nativas de cookies y deja vacía la
colección de esos OSID, sin inventar credenciales de servicio.

Si se obtuvo el token maestro pero falla una etapa posterior, el avance se
guarda con permisos `0600`, separado del archivo final. Puede reanudarse sin
volver a intercambiar el OAuth:

```bash
.venv/bin/python scripts/ghunt_session.py resume --credentials .ghunt/creds.m
```

Solo una validación correcta publica `creds.m`; un avance pendiente no activa
GHunt. Si falla `intercambio_oauth` y no hay avance, hace falta una autenticación
nueva de Companion. El tipo de error y la etapa se muestran sin incluir
respuestas de autenticación, cookies ni tokens.

En el `.env` de Person Map, poner la **ruta absoluta** del archivo generado:

```dotenv
GHUNT_ENABLED=true
GHUNT_CREDENTIALS_FILE=/ruta/person-map/backend/.ghunt/creds.m
```

Reiniciar el backend para cargar esa configuración. Comprobar la sesión con:

```bash
.venv/bin/python scripts/ghunt_session.py check
```

También puede reutilizarse un `creds.m` propio generado con la CLI oficial.
La sesión se comprueba y regenera con las funciones originales de GHunt.
Las escrituras durante consultas son atómicas y mantienen permisos privados;
el directorio debe ser escribible por el backend. En Docker, montar un
directorio de sesión persistente con permisos para el usuario `app`; no basta
un archivo de solo lectura, porque GHunt renueva su sesión y tokens.

Un master token revocado exige volver a iniciar sesión en una ruta nueva y
actualizar la configuración. La integración nunca abre diálogos interactivos
dentro de una petición HTTP. Sin sesión, las otras herramientas siguen
trabajando y GHunt registra `session_not_configured`, sin declarar cuentas
inexistentes. La disponibilidad de un archivo no certifica una sesión válida.

## Configuración y límites

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `GHUNT_ENABLED` | `true` | Registrar consultas cuando haya entradas; sin sesión devuelve diagnóstico |
| `GHUNT_PYTHON` | Runtime local aislado | Ruta al Python del entorno de GHunt |
| `GHUNT_CREDENTIALS_FILE` | Vacío | Archivo de sesión configurado por el administrador |
| `GHUNT_SERVICES` | `["maps","calendar","play_games"]` | Servicios adicionales a PeoplePa |
| `GHUNT_MAX_QUERIES` | `3` | Consultas de correo/GAIA por investigación |
| `GHUNT_MAX_DRIVE_FILES` | `3` | Archivos/carpetas explícitos por investigación |
| `GHUNT_WORKER_TIMEOUT` | `180` | Segundos máximos para el lote, incluida la espera de sesión |
| `GHUNT_REQUEST_TIMEOUT` | `20` | Segundos por petición |
| `GHUNT_MAX_REQUESTS` | `80` | Peticiones por worker, incluida autenticación |
| `GHUNT_MAX_EVENTS` | `20` | Próximos eventos de una sola página; no recorre toda la historia |

El límite de lote conserva los resultados ya obtenidos si una consulta agota
el tiempo. Cada respuesta se limita a 4 MiB. Todas las peticiones del worker
viajan al transporte del backend: HTTPS, destinos Google permitidos, DNS/IP
públicas y presupuestos global/por host compartidos. El cliente del hijo
gestiona sus cookies; las consultas anónimas no heredan las del padre.
Cancelar o agotar el tiempo termina el proceso hijo. Una exclusión mutua por
proceso serializa el uso de la sesión; se conserva la configuración de un
worker del backend que ya requiere el EventBus.

Los estados distinguen `observed`, `not_found`, `no_public_profile`,
`not_public`, `session_invalid`, `session_expired`, `authentication_failed`,
`access_denied`, `rate_limited`, `upstream_error`, `timeout` y límites de
presupuesto. Errores y bloqueos no son ausencia. La cobertura se guarda en
runtime/diagnósticos; cambiar de sesión o configuración invalida la cobertura
de GHunt sin borrar la de Maigret. Renovar cookies no reinicia los presupuestos.

El adaptador conserva el perfil si Google envía una portada opcional sin
`metadata.container` o sin imagen: omite esa portada y registra
`incomplete_cover_ignored`. No inventa su procedencia ni la atribuye a
`PROFILE`; las portadas de `CONTACT` tampoco se exportan. Los fallos de parser
conservan el tipo de error en diagnósticos, sin mensajes ni respuestas crudas.

## Motores, MCP y visualización

El registry registra `ghunt`; reglas, agente e híbrido la descubren como las
demás herramientas. MCP expone `get_ghunt_capabilities`, `ghunt` y el estado
del módulo en `get_investigation_context`. REST expone
`GET /api/v1/ghunt/capabilities`, sin rutas locales, cookies ni tokens.

Ejemplo del objeto `inputs` en una llamada MCP a `ghunt`:

```json
{
  "identifiers": [{"id_type": "gaia_id", "value": "123456789012345678901"}]
}
```

También acepta `email` o `candidate_urls` con enlaces explícitos a Drive/Docs.
La llamada necesita los identificadores habituales de expediente/sesión de
Person Map. `force` permite refrescar cobertura como en otras herramientas.

Los hallazgos usan tipos ya existentes (`google_account`, `social_account`,
`search_mention`, `document`). El inspector muestra GAIA, estadísticas de Maps,
servicios, eventos, colaboradores y contexto de acceso; los estados de
consulta quedan en el expediente y la trazabilidad. No hay migración de BD.

Se retiró el antiguo POST de lookup de Gmail: una página genérica de login
ya no produce una cuenta activa con confianza 0,85. Scholar ahora se consulta
una vez por nombre/universidad, sin repetir por cada correo ni atribuir la
institución consultada como si se hubiera observado en el resultado.

La siguiente revisión de `google_account_osint` permite leer perfiles Scholar
por URL y observa nombre, afiliación, dominio verificado y métricas desde la
tabla del autor. Los bloqueos quedan como diagnóstico; una tarjeta de búsqueda
puede mantenerse como candidato sin inventar esos datos. Los enlaces ORCID
observados admiten pivotes tipados. YouTube conserva canales candidatos y el
verificador puede vincular un ID a su handle mediante metadatos estructurados.
Verificar la existencia del perfil no confirma que pertenezca al objetivo.
Son consultas públicas complementarias con cobertura persistente y límites
propios; no cambian la sesión ni el entorno nativo de GHunt. Véase
[motor de correo y Google públicos](HOLEHE.md#github-y-google-públicos).

## Verificación

`backend/tests/test_ghunt.py` ejecuta la biblioteca **real instalada** en un
subproceso con HTTP simulado: perfil, GAIA, Maps, Calendar sin autenticación,
Play Games protobuf, Drive público/privado, contactos del operador excluidos,
fallos de sesión, límites, cancelación y continuidad del motor tradicional.
`test_mcp_workspace_db.py` verifica también GAIA por MCP, persistencia de
hallazgos y diagnósticos, selección explícita de correo/GAIA y reutilización
de cobertura después del pivote, en un esquema temporal.

```bash
cd backend
.venv/bin/pytest tests/test_ghunt.py -q
.venv/bin/pytest tests/test_mcp_workspace_db.py -m db -q
```

**2026-10-14 (Lima):** sesión local configurada y consulta real al correo del
último análisis, solicitada por el operador. Se detectó y corrigió un
`KeyError` del parser nativo por una portada sin contenedor. La repetición con
el adaptador corregido completó siete peticiones y recuperó un perfil Google
con GAIA y avatar; Maps y Play Games respondieron `empty`, Calendar
`not_public`. Fue una verificación directa de GHunt: no reescribe los hallazgos
del análisis histórico ni demuestra registros en servicios ajenos a Google.
Autenticación y disponibilidad real de los endpoints quedan pendientes de esa
sesión. El backend en ejecución debe reiniciarse y el frontend reconstruirse
para cargar los cambios; estas pruebas no reinician los servicios habituales.

Validación realizada: suite general **596 aprobadas, 9 excluidas**; después
se añadió una prueba de login local (sesión completa, permisos y ausencia de
tokens en salida). Las últimas regresiones de GHunt/MCP/traza/agente/híbrido
pasaron **62 pruebas** y PostgreSQL **8**, incluidos correo y GAIA por MCP.
TypeScript y ESLint del inspector pasaron; también se comprobó su proyección
de GAIA, estadísticas, acceso, eventos y colaboradores con datos sintéticos.
El lock aislado pasó la comprobación offline y el manifiesto/lock del backend
permanecen sin cambios. El Dockerfile se adaptó; no se construyó una imagen
Docker durante esta validación.

Corrección de autenticación: se reprodujeron con HTTP simulado la renovación
nativa sin OSID, el fallo posterior al intercambio con reanudación, el rechazo
de OAuth y la omisión de secretos en salida. Un intento real de autenticación
autorizado por el operador devolvió `GHuntAndroidMasterAuthError` en
`intercambio_oauth`; no se creó una sesión utilizable. La corrección queda
pendiente de validar con una autenticación nueva introducida localmente.
Las regresiones finales de GHunt/MCP pasaron **39 pruebas**, además de las
**8 de PostgreSQL**. El cliente HTTP del worker/login es el nativo de GHunt,
con su manejo explícito de cookies y el transporte compartido de Person Map.

Validación posterior con una sesión nueva: `ghunt_session.py check` devolvió
`authenticated` mediante una sola petición real. Google respondió con una
redirección regional `accounts.google.com.pe/accounts/SetSID`; el adaptador
permite leer esa cabecera para `CheckCookie`, sin seguirla ni habilitar
peticiones a dominios regionales. Las regresiones de GHunt/MCP pasaron
**45 pruebas**, incluidos los límites de esa excepción. La ruta local quedó
configurada en el `.env` privado. Sigue pendiente una consulta real de perfil;
validar la sesión no certifica la disponibilidad de todos los servicios.
