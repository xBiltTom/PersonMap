# Registro de fuentes y técnicas OSINT

Fichero **vivo**. Materializa el principio de *no reinventar la rueda*: antes de
escribir cualquier módulo nuevo se busca si el dato o la técnica ya existen en un
proyecto con licencia compatible, y aquí se deja constancia de qué se adoptó, de
dónde, bajo qué licencia y cuándo se comprobó por última vez que sigue vivo.

El ecosistema OSINT se degrada rápido: Holehe, durante años la referencia en
enumeración de correos, lleva sin mantenimiento y con módulos rotos. **Un
endpoint que hoy responde puede estar muerto el mes que viene sin previo aviso.**
De ahí que cada fase del plan empiece re-verificando esta tabla.

## Cómo revisar

1. Re-comprobar con `curl` cada endpoint de la tabla "Fuentes en uso".
2. Revisar los repos de la tabla "Proyectos de referencia" por cambios de
   licencia, abandono o técnicas nuevas.
3. Actualizar la columna *Última verificación* y el *Estado*.
4. Anotar en el docstring del módulo que adopte una técnica el repo de origen y
   su licencia, como ya hacen `app/tools/http_client.py` y
   `app/tools/google_account_osint.py`.

Estados: 🟢 operativa · 🟡 degradada · 🔴 muerta · ⚪ evaluada, no adoptada

---

## Fuentes en uso

| Fuente | Endpoint / dato | Key | Estado | Última verificación | Usada por |
|---|---|---|---|---|---|
| **WhatsMyName** | `wmn-data.json` bundleado, **667** sitios utilizables | No | 🟢 | 2026-09-04 | `username_finder`, vía `dataset_adapter` |
| **Maigret** | `maigret-data.json` vendorizado @ `8f42a42` | No | 🟢 | 2026-09-04 | `username_finder`. De 4.020 sitios quedan **1.774** tras descartar deshabilitados, protegidos, adultos y los que no traen validación de contenido |
| **crt.sh** | `crt.sh/?q={dominio}&output=json` | No | 🟡 **intermitente** | 2026-09-04 | `domain_finder` — Certificate Transparency. Medido el mismo día: 1 de 4 por la mañana, 6 de 6 por la tarde |
| **XposedOrNot** | `api.xposedornot.com/v1/check-email/{email}` | No | 🟢 | 2026-09-04 | `breach_checker` |
| **OpenAlex** | API de autores y trabajos | No | 🟢 | 2026-09-04 | `academic_finder` |
| **Gravatar** | Perfil por hash MD5 del correo | No | 🟢 | 2026-09-04 | `gravatar_deep`, `email_enumerator` |
| **Keybase** | API pública de resolución de identidad | No | 🟢 | 2026-09-04 | `keybase_resolver` |
| **MediaWiki** | API de contribuciones | No | 🟢 | 2026-09-04 | `wikipedia_edits` |
| **GitHub** | API pública sin autenticar | No | 🟢 | 2026-09-04 | `github_deep_scanner`, `email_checker` |
| **Tavily** | `POST api.tavily.com/search` | Sí (gratuita) | 🟢 | 2026-09-04 | `search_dorker` — motor principal. 1.000 créditos/mes; 1 crédito por búsqueda `basic`, 2 por `advanced` |
| **DuckDuckGo** | Scraping HTML de resultados | No | 🟡 | 2026-09-04 | `search_dorker` — motor de respaldo automático. Responde HTTP 202, no 200 |
| **Google (Scholar/YouTube)** | Endpoints públicos sin key | No | 🟡 | 2026-09-03 | `google_account_osint` — el `lookup` de Gmail es históricamente inestable |
| **Gemini** | `generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent` | Sí (gratuita) | 🟢 | 2026-09-04 | Capa 2 del motor `hybrid`, agente `agentic` y narrativa. Verificado que emite `functionCall` con nuestro esquema de herramientas |
| **Hudson Rock Cavalier** | `cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email\|username` | No | 🟢 | 2026-09-04 | `infostealer_checker`. **Solo con consentimiento explícito.** Límite de 50 req/10 s por host, respetado con `register_host_rate_limit` |

### Trampas verificadas en producción

**Tavily — el parámetro `exact_match` no sirve.** Está documentado en la
referencia oficial, pero probado contra la API real devuelve **cero resultados
en todos los casos**, con y sin comillas en la consulta, y sin ningún error:
HTTP 200 y `results: []`. Enviarlo deja el dorking mudo en silencio. Las
comillas dentro de la propia consulta sí funcionan, así que no se envía el
parámetro.

**Tavily busca por relevancia semántica, no por coincidencia literal.** Un dork
de un correo inexistente (`"jperez@untumbes.edu.pe"`) devuelve la portada de
`untumbes.edu.pe` con score 0.55. En OSINT ese falso positivo es peor que no
obtener nada, porque acaba en el expediente de una persona concreta. De ahí que
`search_dorker` imponga la exactitud del lado del cliente
(`tavily_require_literal_match`), exigiendo que **todos** los términos
entrecomillados del dork aparezcan en el título, el extracto o la URL.

**El listado de modelos de Gemini incluye modelos que la clave no puede usar.**
`v1beta/models` devuelve 50 entradas, pero `gemini-2.5-flash` responde **404
"no longer available to new users"** pese a figurar en ella, y
`gemini-2.0-flash` ya no aparece. Peor aún: de dos modelos que sí responden
200, `gemini-3.5-flash` **no emite `functionCall`** con el prompt de
refinamiento y `gemini-3.6-flash` sí. Comprobar con `curl` el modelo concreto y
**la capacidad concreta** que se va a usar, no solo que el proveedor responda.

**Fijar versión explícita del modelo, nunca un alias.** `gemini-flash-latest`
funciona, pero apunta a un modelo distinto cada pocas semanas. Las mediciones
del artículo dejarían de ser reproducibles, por el mismo motivo por el que el
dataset de Maigret se vendoriza en vez de sincronizarse.

**Hudson Rock — `top_logins` no son los servicios afectados.** El nombre lo
sugiere y la primera implementación los mapeó a `affected_services`, pero
probado contra la API real son **correos enmascarados**
(`e**********@gmail.com`). Presentarlos como "servicios afectados" habría metido
una afirmación falsa en el expediente de una persona concreta. No se persisten:
lo accionable ya lo dice `total_user_services`.

**Hudson Rock rellena lo que no sabe con la cadena `"Not Found"`.** `ip` y
`malware_path` no vienen ausentes, vienen con ese texto. Guardarlo tal cual
ponía "Ruta del malware: Not Found" en el informe, que parece un fallo del
sistema en vez de un dato que no existe. Se descartan por lista de rellenos.

**El endpoint `search-by-domain` da estadística institucional, sin individuos.**
Verificado con `unmsm.edu.pe` el 2026-09-04: 3.232 cuentas de personal y 8.048
de estudiantes comprometidas, con la última infección cuatro días antes. **No
está integrado** —sería un dato sobre la institución, no sobre la persona, y
mezclarlo en su expediente rompería el modelo de atribución—, pero es material
de concientización de primer orden para un panel de contexto del informe.

**Maigret — el 36 % de sus sitios no puede decir que no.** 1.098 de 3.077 no
traen ninguna cadena de validación: su único criterio es el código de estado, y
muchos responden 200 a cualquier URL de perfil. Medido sobre un alias sintético
que no existe en ningún sitio, producían **255 "cuentas", todas falsas**. Se
exige que un sitio de Maigret traiga alguna forma de comprobar el contenido.
Un ranking alto **no** es sustituto: WordPressOrg tiene ranking 12, ninguna
cadena, y responde 200 a un alias inexistente.

**Maigret marca lo adulto con etiquetas, no con la categoría de WhatsMyName.**
Sin traducirlas, 19 sitios porno se colaban en el catálogo de una herramienta
educativa cuyo informe se le enseña a la persona investigada.

**El ecosistema de enumeración por correo se ha cerrado.** Sondeados en vivo
Instagram, Imgur, Archive.org, Zoho, Mercado Libre, Xbox y Bitmoji: ninguno
sirve (429 inmediato, 403, o no distinguen entre un correo real y uno
sintético). Es coherente con que Holehe lleve años roto. De las 20 sondas que el
proyecto ya tenía, **7 apuntaban a endpoints muertos y 1 producía un falso
positivo garantizado**; ver el historial de revisiones.

### Licencias que obligan a atribución

- **WhatsMyName** — *CC BY-SA 4.0*, © 2015-2026 Micah Hoffman y colaboradores.
  El ShareAlike **se contagia a cualquier dataset derivado que se redistribuya**.
  Por eso el dataset se mantiene como fichero independiente y la normalización
  con otras fuentes ocurre en memoria (`app/tools/dataset_adapter.py`), nunca en
  un fichero fusionado. Hay un test que lo vigila.
- **Maigret** — *MIT*, © soxoj y colaboradores. Snapshot vendorizado y fijado al
  commit `8f42a42d0ebb117f265eeaf6c75ebda5249a79b4` (2026-09-04). No se
  sincroniza en caliente: un fichero remoto sin firmar que decide a qué miles de
  hosts se manda tráfico es un vector de cadena de suministro, y una lista
  cambiante rompe la reproducibilidad de las mediciones del artículo.

---

## Fuentes verificadas y pendientes de integrar

Comprobadas en vivo con `curl` el 2026-09-03. Todas gratuitas y sin API key,
conforme a la restricción del proyecto.

| Fuente | Endpoint | Estado | Aporta | Fase |
|---|---|---|---|---|
| **Avatar GitHub** | `github.com/{user}.png` | 🟢 HTTP 200, `image/jpeg` | Cosecha activa de avatares | 5 |
| **Avatar Gravatar** | `gravatar.com/avatar/{md5}?d=404` | 🟢 HTTP 200 (404 si no existe) | Cosecha activa de avatares; el `d=404` da señal binaria limpia | 5 |

> **Nota sobre el snapshot de Maigret.** Maigret se auto-actualiza desde GitHub
> cada 24 h. Aquí **no** se replica ese comportamiento: un fichero remoto sin
> firmar que define a qué ~3000 hosts se manda tráfico es un vector de cadena de
> suministro, y una lista cambiante rompe la reproducibilidad que necesita el
> artículo. Se vendoriza un snapshot fijado por commit, actualizable a mano.

---

## Proyectos de referencia

Se revisan al abrir cada fase. **No se añaden como dependencia de ejecución**: se
trae el dato o la técnica, reimplementados sobre `app/tools/http_client.py`.

| Proyecto | Licencia | Estado | Qué aporta |
|---|---|---|---|
| [soxoj/maigret](https://github.com/soxoj/maigret) | MIT | 🟢 activo, ~23k ★ | Dataset de 3000+ sitios con `regexCheck`, `alexaRank`, `absenceStrs`, `protection` |
| [WebBreacher/WhatsMyName](https://github.com/WebBreacher/WhatsMyName) | CC BY-SA 4.0 | 🟢 activo | Dataset ya integrado; conviene refrescarlo periódicamente |
| [kaifcodec/user-scanner](https://github.com/kaifcodec/user-scanner) | MIT | 🟢 activo, 4.6k ★ | Sucesor de facto de Holehe: 175+ vectores de correo, 290+ de username |
| [megadose/holehe](https://github.com/megadose/holehe) | GPL-3.0 | 🔴 sin mantenimiento | Técnica original de enumeración silenciosa. Módulos rotos; usar user-scanner |
| [megadose/ignorant](https://github.com/megadose/ignorant) | GPL-3.0 | ⚪ **descartado** | Enumeración de teléfono vía flujos de reset. **No se adopta**: dispara SMS/emails reales a un tercero que no ha consentido — no es OSINT pasivo |
| [mxrch/GHunt](https://github.com/mxrch/GHunt) | AGPL-3.0 | 🟢 activo | Metodología de OSINT de cuentas Google. Sus funciones más ricas (Maps, Calendar) exigen cookies de sesión, inviables en un backend desatendido |
| [microlinkhq/unavatar](https://github.com/microlinkhq/unavatar) | MIT | ⚪ referencia | Lista de 74+ proveedores de avatar. **Su API no se consume**: limita a 25 req/día por IP en anónimo; se implementan los patrones de URL directos |
| [moj-analytical-services/splink](https://github.com/moj-analytical-services/splink) | MIT | 🟢 activo | Fellegi-Sunter con estimación EM no supervisada de los pesos m/u |
| [jivoi/awesome-osint](https://github.com/jivoi/awesome-osint) · [edwardtay/awesome-OSINT](https://github.com/edwardtay/awesome-OSINT) | — | 🟢 | Listas curadas para descubrir fuentes nuevas |

---

## Fuentes evaluadas y descartadas

| Fuente | Motivo |
|---|---|
| **HaveIBeenPwned API v3** | De pago (desde $4.39/mes). El proyecto se restringe a fuentes gratuitas sin key; XposedOrNot y Hudson Rock cubren el caso |
| **Brave Search API** | Requiere registro y key ($5/mes de crédito gratuito). Se optó por Tavily, que da 1.000 créditos/mes y devuelve JSON pensado para agentes |
| **SerpApi / Bing Visual Search** | De pago. `reverse_image_search.py` queda implementado pero desactivado; la cosecha activa de avatares lo sustituye sin coste |
| **SearXNG público** | La salida JSON está desactivada en la mayoría de instancias públicas; auto-hospedado recibe CAPTCHA de Google/Brave/Startpage desde una sola IP |
| **PimEyes / FaceCheck.ID** | De pago y legalmente delicados (datos biométricos). Fuera del alcance de una herramienta de concientización |

---

## Historial de revisiones

| Fecha | Alcance | Resultado |
|---|---|---|
| 2026-09-03 | Revisión inicial del ecosistema para el plan de ejecución | Se verificaron en vivo Hudson Rock, crt.sh y los patrones directos de avatar (todos 🟢, sin key). Se midió el dataset de Maigret (3653 sitios). Se descartaron `ignorant` por motivos éticos y HIBP/Brave/SerpApi por coste |
| 2026-09-04 | Integración de Tavily como motor de dorking | 🟢 operativa. Dos trampas detectadas solo al probar contra la API real, no en los tests con mock: `exact_match` devuelve cero resultados siempre, y la búsqueda es semántica (un correo inexistente devuelve la portada de su dominio). Ambas mitigadas en `search_dorker`; ver "Trampas verificadas en producción" |
| 2026-09-04 | Barrido completo al abrir la **Fase 3** (`hybrid`) | 🟢 XposedOrNot, OpenAlex, Gravatar (404 limpio), Keybase, MediaWiki, GitHub API y avatar, Hudson Rock, Tavily y el `data.json` de Maigret (1,66 MB). 🟡 DuckDuckGo responde **202**, no 200. 🔴→🟡 **crt.sh se ha degradado**: 1 de 4 peticiones dio 200 y tres dieron 502, lo que obliga a reintentos en la Fase 4.4 |
| 2026-09-04 | Auditoría en vivo de las 20 sondas de correo (Fase 4.3) | 🔴 **0 útiles, 19 mudas, 1 falso positivo garantizado.** La sonda de Quora marcaba TODOS los correos como registrados: su endpoint dejó de ser una API y devuelve la portada HTML de 81 KB, mientras la comprobación buscaba la palabra `"false"`, que aparece en cualquier JavaScript. Llegó a un expediente real. Auditados los 20 endpoints: 7 muertos (404/405/401) y 5 devuelven HTML donde el código espera JSON. Retiradas 8 sondas. **La de Vimeo hacía POST a `/log_in` con contraseña**, es decir, un intento de acceso real contra la cuenta de una persona: eliminada por el mismo criterio que descarta `ignorant` |
| 2026-09-04 | Integración de Maigret y crt.sh (Fases 4.1 y 4.4) | 🟢 Catálogo unificado de 2.441 sitios. Frente a solo WhatsMyName: **+48 % de cobertura (86 → 127 hallazgos sobre `@torvalds`) a cambio de 5 falsos positivos por alias**, todos con atribución 0.10. `regexCheck` ahorra el 20 % de las peticiones en alias con punto o guion. crt.sh operativa pero intermitente |
| 2026-09-04 | Integración de Hudson Rock (Fase 4.2) | 🟢 operativa, con consentimiento explícito. Tres trampas que **solo** aparecieron contra la API real: `top_logins` son correos enmascarados y no servicios afectados; `ip` y `malware_path` traen la cadena `"Not Found"` en vez de venir ausentes; y los totales aparecen tanto por registro como en la raíz. Ninguna se habría visto con los tests de mock, que es exactamente la lección de Tavily repitiéndose |
| 2026-09-04 | Recuento real del catálogo de WhatsMyName | Los documentos decían **716 sitios**; los utilizables son **667**. La cifra antigua incluía entradas NSFW, archivadas y sin `uri_check`, que el cargador ya descartaba. Corregido aquí y expuesto en las métricas de cada investigación (`config_username_catalog_available`) para que el dato no vuelva a divergir del código |
| 2026-09-04 | Alta de Gemini como proveedor LLM (cierre de la Fase 3) | 🟢 `gemini-3.6-flash` operativo y verificado con function calling. Dos trampas detectadas solo con `curl`: el listado de modelos incluye `gemini-2.5-flash`, que devuelve 404 para claves nuevas, y `gemini-3.5-flash` responde 200 pero no emite `functionCall`. La primera corrida real recibió además un **503 "high demand"** en el segundo turno; el motor degradó como estaba previsto y conservó el barrido heurístico completo |
| 2026-09-04 | Revisión de reutilización para la Fase 3 | **No se adoptó ningún proyecto externo, y es la conclusión correcta.** El híbrido es orquestación interna: encadena dos motores que ya existían en el repositorio. Lo único importable habría sido un patrón de orquestación de agentes, y traerse un framework (LangGraph, CrewAI y similares) habría sustituido la arquitectura `BaseTool` + `ToolRegistry` en lugar de aprovecharla — justamente lo que el principio de no reinventar la rueda pretende evitar. La referencia seguida es §5.3 de `ANALISIS_OSINT_MUNDIAL.md`, corregida a "tercera estrategia" en vez de reemplazo |
