# Auditoría de las seis redes sociales principales

Fecha: 2026-10-07. Código revisado: commit `09f051f`.

Conclusión: las seis redes están en el catálogo efectivo de 500 entradas, pero
su integración no está óptima. La cobertura de catálogo, la detección de
existencia, el enlace del recurso y la extracción de metadatos son capacidades
distintas y actualmente no están resueltas de forma uniforme.

## Método y límites

- Inspección de catálogo, enumeración de alias/correos, extracción de URLs,
  verificación, búsquedas y presentación de enlaces.
- Reproducciones locales de formatos de URL y respuestas HTTP/JSON.
- 16 consultas GET externas a recursos públicos de organizaciones/plataformas
  y un alias aleatorio de control. Sin autenticación, cookies de sesión,
  recuperación de cuentas, altas ni consultas de correos de terceros.
- 85 pruebas existentes relevantes pasaron.

La primera ejecución restringida no conectó. Los resultados siguientes
proceden de la ejecución con acceso de red permitido. Representan una muestra
desde este entorno y momento, no una certificación de disponibilidad mundial
ni de todas las cuentas. No se modificó el comportamiento de la aplicación
durante esta revisión.

Evidencia reproducible de la revisión:

- [Resultados de las 16 consultas externas](audits/common-social-2026-10-07-live.json).
- [Reproducciones locales de rutas y validaciones](audits/common-social-2026-10-07-code.json).

## Resultados de consultas externas

| Red | Recurso de referencia | Sonda del catálogo | Control negativo / contraste |
| --- | --- | --- | --- |
| X | `x.com/NASA` | La API de disponibilidad devolvió 200 y `reason=invalid_username`; `_matches` lo rechazó. | La página de NASA devolvió 200 y metadatos de perfil; el alias aleatorio devolvió 404. La API del control devolvió `available`. |
| Instagram | `instagram.com/instagram` | 200 con título genérico `Instagram`, sin metadatos OpenGraph; `_matches` lo rechazó. | El alias aleatorio recibió una página igualmente genérica, también 200. La respuesta no permite discriminar existencia. |
| Facebook | `facebook.com/facebook` | 400 con título `Error`; `_matches` lo rechazó. | El control también recibió 400. El resultado es un fallo de consulta, no evidencia de inexistencia. |
| TikTok | `tiktok.com/@tiktok` | oEmbed devolvió 503; `_matches` lo rechazó. | oEmbed del control devolvió 400. Las páginas de ambos alias devolvieron 200 con título genérico y sin OpenGraph. |
| YouTube | `youtube.com/@YouTube` | 200 y `_matches=True`. | El control devolvió 404 y `_matches=False`. Esta ruta sí discriminó en la muestra. |
| Snapchat | `snapchat.com/@teamsnapchat` | 200 con título y OpenGraph del perfil, pero `_matches=False`. | El control devolvió 404. La cadena inglesa `is on Snapchat!` del catálogo no reconoció la página recibida en español. |

## Defectos reproducidos en el código

1. **Portada presentada como cuenta identificada.** `email_enumerator` conserva
   `https://x.com` al detectar una señal por correo y muestra `Cuenta Activa`.
   No dispone de un usuario de perfil. `entityInspector` clasifica `metadata.url`
   como enlace de perfil, sin separar web del servicio y perfil encontrado.
   Además, el control negativo de correo considera aprobado un fallo de la
   sonda del alias inventado: ese caso necesita estado inconcluso.
2. **Pérdida de identidad en Facebook.**
   `facebook.com/profile.php?id=123456789012345` y otro ID distinto se convierten
   ambos en `facebook.com/profile.php`, con el supuesto alias `profile.php`.
   Esto pierde el ID, confunde recursos y puede introducir un alias falso en
   los pivotes. Es un fallo de `parse_social_profile`, independiente de red.
3. **YouTube incompleto.** El extractor y el verificador rechazan
   `/channel/<ID>`, handles con punto y `/c/<nombre>/about`. Las dos rutas
   antiguas del catálogo producen URLs terminadas en `/about` que el verificador
   posterior no admite. Los handles internacionales/codificados tampoco están
   cubiertos. La búsqueda específica de canales está ligada a ciertos correos
   Google/educativos y toma hasta tres coincidencias de regex del HTML, sin
   extraer los resultados estructurados de canales.
4. **Snapchat incompleto.** No hay ruta dedicada en `PROFILE_ROUTES`, por lo
   que el extractor no reconoce ni `/@usuario` ni `/add/usuario`. El verificador
   puede usar el catálogo para la forma exacta con `www`, pero pierde variantes
   sin ese subdominio. El patrón del catálogo también rechaza `abc1def` y
   acepta `abcd1def` por coincidencia parcial, pese a permitir Snapchat letras
   y números. No tiene anclaje final y su mínimo tampoco coincide con la
   especificación oficial.
5. **Validación frágil de JSON en X.** `{"reason":"taken"}` se acepta, mientras
   `{"reason": "taken"}` se rechaza por espacios. La disponibilidad de un alias
   debe interpretarse como JSON y no sustituir la comprobación de perfil.
6. **TikTok acepta un autor diferente.** Una respuesta JSON de oEmbed que
   contiene `author_url` para otro usuario pasa `_matches` para el alias
   consultado. No se compara ese identificador ni se conserva la información
   estructurada del autor. La falta de oEmbed en cuentas privadas o menores
   tampoco demuestra inexistencia.
7. **Marcadores de Facebook demasiado generales.** Un HTML simulado con
   `__isProfile`, alias correcto y `rsrcTags` se rechaza porque `rsrcTags` es
   una cadena de ausencia incorporada al catálogo. La reproducción demuestra
   el conflicto del criterio; la respuesta externa 400 no permite medir cuántos
   perfiles reales afecta hoy.
8. **Búsqueda y estados incompletos.** El filtro social de `search_dorker` no
   incluye YouTube ni Snapchat, aunque una búsqueda general podría encontrarlos.
   `_detect_platform` todavía clasifica por subcadenas de la URL, no por host.
   La enumeración devuelve lista vacía tanto para un alias inexistente como
   para bloqueos o errores, sin estados por plataforma equivalentes a los del
   verificador. En el verificador, una página de login cuyo `og:title` es
   genérico puede terminar como `not_profile` en lugar de bloqueo/inconcluso.

## Implementación recomendada, en orden

1. Separar **señal de registro por correo**, **URL candidata**, **perfil público
   observado** y **consulta inconclusa**, también en las etiquetas y enlaces de
   la interfaz. La web principal del servicio debe ser `service_url`; solo un
   recurso identificado debe tener `profile_url`.
2. Corregir el parser común: Facebook por ID, YouTube por ID/handle/rutas
   antiguas/Unicode y Snapchat por sus rutas públicas. Mantener IDs estables
   separados de alias y no pivotar un ID o `profile.php` como nombre de usuario.
3. Mantener WhatsMyName/Maigret para cobertura y añadir adaptadores específicos
   para estas seis redes: interpretar JSON estructurado, cotejar identificadores
   y usar metadatos de perfil independientes del idioma. Aplicar controles
   negativos tanto a la sonda principal como a cualquier respaldo adoptado.
4. Para X, complementar la disponibilidad de alias con consulta del perfil
   público y búsquedas indexadas cuando la primera sonda no discrimine. Para
   TikTok, conservar y validar `author_url`, `author_name` y la información de
   oEmbed; el HTML interno solo puede usarse si está públicamente disponible.
5. Desacoplar la búsqueda de canales de YouTube del proveedor de correo.
   Su API oficial ofrece `forHandle`, `forUsername` e `id` como opción adicional.
   Completar el descubrimiento indexado de YouTube y Snapchat usando los motores
   ya integrados. Un resultado indexado conserva su procedencia y estado de
   candidato si no puede comprobarse el perfil directamente.
6. Registrar por plataforma bloqueos, respuestas genéricas, errores y ausencia
   explícita. Ante acceso restringido, conservar el resultado inconcluso y la
   evidencia indexada disponible; no evadir login o CAPTCHA.
7. Añadir fixtures reales y pruebas de regresión para cada ruta y resultado
   anterior, más una prueba de red pequeña por plataforma con perfil de
   referencia y control. Versionar los overrides del catálogo sin alterar
   silenciosamente sus snapshots originales.

## Fuentes oficiales contrastadas

- [URLs de canales de YouTube](https://support.google.com/youtube/answer/6180214).
- [Reglas de handles de YouTube](https://support.google.com/youtube/answer/11585688?hl=en).
- [YouTube Data API: channels.list](https://developers.google.com/youtube/v3/docs/channels/list).
- [TikTok: oEmbed para perfiles de creadores](https://developers.tiktok.com/docs/en/embed-creator-profiles).
- [Snapchat: reglas de usuario](https://help.snapchat.com/hc/en-us/articles/7012349845140-How-do-I-change-my-Snapchat-username).
- [X: usuario y URL del perfil](https://help.x.com/en/managing-your-account/change-x-handle).

Los perfiles públicos encontrados no demuestran por sí solos que pertenezcan
a la persona del expediente. La disponibilidad externa y la atribución son
evaluaciones separadas.

## Mejoras implementadas después de la auditoría

El motor social pasa a versión 3 en la huella de ejecución. Los snapshots
vendorizados se conservan; las correcciones de Snapchat y Facebook se aplican
en memoria al catálogo.

- La enumeración por correo produce `email_registration`, con `service_url` y
  perfil sin identificar. No alimenta pivotes de perfiles. La interfaz muestra
  el servicio y distingue la señal de registro del perfil encontrado. Un
  control negativo sin respuesta explícita queda sin comprobar.
- El parser conserva IDs de Facebook (`profile.php?id=`, rutas numéricas y
  `people`), canales de YouTube y handles internacionales/codificados. Los IDs
  no se convierten en alias para barrer otras plataformas. Admite Snapchat
  `@`/`add`, Threads, Bluesky, Keybase y VK mediante dominios y rutas completos.
- El enumerador prepara hasta seis URLs candidatas por alias para verificar
  las redes principales incluso si falla el catálogo. Son solicitudes
  derivadas, no hallazgos. El orquestador continúa cuando estas solicitudes
  habilitan nuevas herramientas, aunque la ronda no encuentre cuentas.
- X interpreta JSON estructurado; TikTok exige que `author_url` corresponda al
  usuario solicitado. El verificador puede comprobar el oEmbed de TikTok, sin
  tratar un oEmbed no disponible como prueba de inexistencia.
- Snapchat valida metadatos y `userProfile.userInfo.username` sin depender del
  idioma. YouTube admite una redirección de ID a handle cuando el ID observado
  coincide. Las páginas genéricas quedan inconclusas; login y retos quedan
  bloqueados. Se mantienen el DNS validado y fijado, los límites de URLs,
  concurrencia, tiempo y reintentos.
- La búsqueda incluye YouTube y Snapchat y consultas sociales por alias;
  clasifica por hostname. DuckDuckGo aplica el mismo requisito de coincidencia
  literal que Tavily. La búsqueda de YouTube funciona también con nombre o
  alias y lee `channelRenderer` de los resultados, no URLs de navegación.
- Los hallazgos presentan el estado candidato/verificado. Verificar existencia
  no verifica que el titular sea la persona investigada.

### Comprobación externa posterior

La [muestra posterior](audits/common-social-2026-10-07-postfix-live.json) ejecutó
nueve consultas de perfiles (seis referencias públicas y tres controles
aleatorios), con peticiones GET adicionales para redirecciones y oEmbed. X,
YouTube y Snapchat fueron verificados y sus tres controles devolvieron 404.
Instagram y TikTok quedaron inconclusos. Facebook devolvió 400 en la ejecución
final; había respondido 200 con metadatos en una ejecución anterior. Esta
variación sigue siendo una limitación de la plataforma, no una prueba de
inexistencia. La extracción ampliada a otras redes se comprobó con fixtures;
no se certificó su disponibilidad externa.

No se hicieron consultas reales por correo ni pruebas contra PostgreSQL.

Validación final: `backend/.venv/bin/python -m pytest -q` ejecutado desde
`backend`: **268 pruebas pasaron**, con **3 excluidas** por sus requisitos de
red/PostgreSQL. Incluye 24 nuevos casos de regresión. Frontend: `tsc --noEmit`
y ESLint de los dos archivos modificados pasaron. También pasó `git diff
--check`. La muestra GET externa descrita arriba se ejecutó por separado.
