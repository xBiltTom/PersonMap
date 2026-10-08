# Validación de recursos públicos de Telegram

El motor social pasa a versión 4. Telegram utiliza un parser específico
compartido entre `username_finder` y `social_verifier`.

## Cambios

- La cabecera de un recurso con nombre y un enlace `tg://resolve?domain=...`
  coincidente son necesarios para verificar la página. HTTP 200, OpenGraph,
  fotos genéricas y enlaces para contactar no bastan. La página genérica de
  contacto queda **inconclusa**, pues tampoco demuestra que una cuenta no exista.
- `noindex` y el título de contacto no se usan por sí solos como ausencia:
  también pueden aparecer en páginas de usuarios reales.
- Los enlaces `telegram.me`, `telegram.dog`, `<usuario>.t.me`, las vistas
  `t.me/s/<usuario>` y los mensajes públicos se normalizan a `t.me/<usuario>`.
  Se conserva el enlace observado como evidencia y se verifica la página del
  recurso, no la publicación. Las variantes no repiten consultas.
- Se excluyen funciones especiales, invitaciones, teléfonos, mensajes privados
  y alias malformados. Se mantienen los límites existentes de red, DNS fijado,
  redirecciones y concurrencia.
- El catálogo usa un formato básico de 5 a 32 caracteres, con letra inicial,
  letras, números y `_`. El mismo filtro se aplica al parser y al catálogo.
  Las rutas especiales quedan reservadas solo para Telegram.
- La clasificación `telegram_peer_type` distingue usuario, bot, grupo y canal
  mediante señales de la página. Si faltan, queda `unknown`; no se infiere que
  algo sea un bot porque su nombre termine en `bot`. El inspector muestra el tipo.
- Se añaden candidatos derivados de Telegram al barrido de alias y `t.me` al
  filtro de búsquedas sociales. Una URL construida no produce un hallazgo por sí sola.
- Los controles negativos que reciben una página genérica quedan sin comprobar.

Las variantes y rutas se contrastaron con la
[documentación oficial de enlaces](https://core.telegram.org/api/links).

## Evidencia externa

La [muestra de HTML](audits/telegram-2026-10-07-html-shape.json) compara el canal
oficial, BotFather, el canal público de Durov y un alias aleatorio. El control
recibió HTTP 200 y una invitación genérica para contactar, sin cabecera de perfil.

La [comprobación del verificador corregido](audits/telegram-2026-10-07-verification.json)
identificó `telegram` y `durov` como canales y `BotFather` como bot. El control
aleatorio quedó inconcluso y no produjo un perfil verificado. Las seis URLs
candidatas representaban cuatro recursos únicos; las variantes `telegram.me`
y `t.me/s/telegram` no repitieron la consulta.

Solo se hicieron GET públicos, sin autenticación, llamadas MTProto, mensajes,
consultas por teléfono ni incorporación a grupos. La existencia de un recurso
no demuestra que pertenezca a la persona investigada. Los alias coleccionables
cortos y los perfiles sin metadatos públicos suficientes siguen fuera de esta
verificación; no se declaran inexistentes.

## Pruebas

- Suite completa de backend: **309 pasaron, 3 excluidas** por requisitos de
  red/PostgreSQL. Incluye 41 casos nuevos de Telegram.
- Suite específica repetida después del ajuste de subdominios: **41 pasaron**.
- Frontend: TypeScript (`tsc --noEmit`) y ESLint del inspector pasaron.
- `git diff --check` pasó. Los GET externos se comprobaron por separado.
