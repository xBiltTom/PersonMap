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
| **WhatsMyName** | `wmn-data.json` bundleado, 716 sitios | No | 🟢 | 2026-09-03 | `username_finder` |
| **XposedOrNot** | `api.xposedornot.com/v1/check-email/{email}` | No | 🟢 | 2026-09-03 | `breach_checker` |
| **OpenAlex** | API de autores y trabajos | No | 🟢 | 2026-09-03 | `academic_finder` |
| **Gravatar** | Perfil por hash MD5 del correo | No | 🟢 | 2026-09-03 | `gravatar_deep`, `email_enumerator` |
| **Keybase** | API pública de resolución de identidad | No | 🟢 | 2026-09-03 | `keybase_resolver` |
| **MediaWiki** | API de contribuciones | No | 🟢 | 2026-09-03 | `wikipedia_edits` |
| **GitHub** | API pública sin autenticar | No | 🟢 | 2026-09-03 | `github_deep_scanner`, `email_checker` |
| **DuckDuckGo** | Scraping HTML de resultados | No | 🟡 | 2026-09-03 | `search_dorker` — frágil, sin API oficial |
| **Google (Scholar/YouTube)** | Endpoints públicos sin key | No | 🟡 | 2026-09-03 | `google_account_osint` — el `lookup` de Gmail es históricamente inestable |

### Licencias que obligan a atribución

- **WhatsMyName** — *CC BY-SA 4.0*, © 2015-2026 Micah Hoffman y colaboradores.
  El ShareAlike **se contagia a cualquier dataset derivado que se redistribuya**.
  Por eso el dataset se mantiene como fichero independiente y la normalización
  con otras fuentes ocurre en memoria, nunca en un fichero fusionado.

---

## Fuentes verificadas y pendientes de integrar

Comprobadas en vivo con `curl` el 2026-09-03. Todas gratuitas y sin API key,
conforme a la restricción del proyecto.

| Fuente | Endpoint | Estado | Aporta | Fase |
|---|---|---|---|---|
| **Hudson Rock Cavalier** | `cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email\|username\|domain` | 🟢 HTTP 200 con datos reales | Logs de infostealer: `date_compromised`, `computer_name`, `operating_system`, `malware_path`, `total_user_services`. Límite **50 req/10 s por host** | 4 |
| **crt.sh** | `crt.sh/?q={dominio}&output=json` | 🟢 HTTP 200 | Certificate transparency → dominios y subdominios personales | 4 |
| **Avatar GitHub** | `github.com/{user}.png` | 🟢 HTTP 200, `image/jpeg` | Cosecha activa de avatares | 5 |
| **Avatar Gravatar** | `gravatar.com/avatar/{md5}?d=404` | 🟢 HTTP 200 (404 si no existe) | Cosecha activa de avatares; el `d=404` da señal binaria limpia | 5 |
| **Maigret `data.json`** | `raw.githubusercontent.com/soxoj/maigret/main/maigret/resources/data.json` | 🟢 MIT | **3653 sitios** (693 `disabled` → **2960 utilizables**; 278 con `protection` TLS a saltar; 1156 con `alexaRank`; 163 con `regexCheck`) | 4 |

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
| **Brave Search API** | Requiere registro y key ($5/mes de crédito gratuito) |
| **SerpApi / Bing Visual Search** | De pago. `reverse_image_search.py` queda implementado pero desactivado; la cosecha activa de avatares lo sustituye sin coste |
| **SearXNG público** | La salida JSON está desactivada en la mayoría de instancias públicas; auto-hospedado recibe CAPTCHA de Google/Brave/Startpage desde una sola IP |
| **PimEyes / FaceCheck.ID** | De pago y legalmente delicados (datos biométricos). Fuera del alcance de una herramienta de concientización |

---

## Historial de revisiones

| Fecha | Alcance | Resultado |
|---|---|---|
| 2026-09-03 | Revisión inicial del ecosistema para el plan de ejecución | Se verificaron en vivo Hudson Rock, crt.sh y los patrones directos de avatar (todos 🟢, sin key). Se midió el dataset de Maigret (3653 sitios). Se descartaron `ignorant` por motivos éticos y HIBP/Brave/SerpApi por coste |
