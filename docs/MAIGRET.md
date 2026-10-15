# Maigret en Person Map

El motor fijado es **Maigret 0.6.6**, con el extra oficial `pdf`. La biblioteca
original ejecuta recetas, motores, activaciones, métodos HTTP, extracción,
enriquecimiento, mutaciones y reintentos en procesos aislados. Person Map adapta
el transporte, los presupuestos y las evidencias a su orquestador.

## Funciones disponibles

| Función de Maigret | Adaptación |
|---|---|
| Usernames | `username_finder`; conserva también las recetas propias de [WhatsMyName](WHATSMYNAME.md) |
| Catálogo completo | `scan_mode=all` o `USERNAME_SCAN_MAX_SITES=0`, incluidas variantes |
| IDs y búsqueda recursiva | `maigret_enricher`, con tipo, origen, controles y presupuesto |
| Extracción desde URLs | Extractores y mutaciones originales mediante el puente HTTP |
| Permutaciones | Generador nativo, hasta tres fragmentos y variantes acotadas |
| Categorías, países, sitios y palabras clave | Filtros globales o `maigret_options` por llamada |
| Cookies | Archivo Netscape del servidor, con alcance por dominio |
| Proxy, Tor e I2P | Transporte del padre y configuración del administrador |
| Emulación de navegador | `curl_cffi` con TLS verificado y DNS público fijado |
| Solver de Cloudflare | FlareSolverr JSON configurado; conserva el estado HTTP real |
| Comprobaciones DNS | Opcionales, con resolución pública y controles; entidades `domain` |
| Informes | Escritores nativos: JSON, NDJSON, CSV, TXT, Markdown, HTML, PDF, XMind, grafo HTML y Neo4j |
| Auditoría | Self-check original sobre sitios elegidos; no modifica el snapshot |
| Actualización de base | Snapshot separado con tag/commit explícito, procedencia y SHA-256 |
| Web, identidad e IA | Se conservan los de Person Map; no se lanzan servicios CLI paralelos |

No se promete disponibilidad universal ni resolución de todos los CAPTCHA.
Las recetas desactivadas y el control conocido de Fanslist se excluyen.
Tor/I2P y el solver necesitan servicios externos. Sus ramas se prueban con
respuestas controladas; disponer de integración no equivale a configurar o
probar una conexión real a esos servicios.

La base incluida tiene 5.897 entradas. La selección pública deduplicada reúne
**5.401 plataformas**: 5.103 recetas Maigret y 298 complementarias. El modo
completo conserva además todas las comprobaciones de WhatsMyName y las variantes
nativas: **5.868 recetas**, sin gateways ni DNS activados. Con límite de 3.400
se incluyen **705 de WhatsMyName y 2.695 de Maigret**. Fast sigue siendo un
prefijo reducido. Hay **25 recetas
para once tipos adicionales**: `orcid`, `steam_id`, `gaia_id`, `vk_id`, `qq_id`,
`bilibili_id`, `yandex_public_id`, `yelp_userid`, `ok_id`, `wikimapia_uid` y
`uidme_uguid`. También hay cuatro recetas Tor, una I2P y siete DNS.

Las capacidades efectivas están en `GET /api/v1/maigret/capabilities` y MCP
`get_maigret_capabilities`.

## Formulario y orquestador

El formulario admite IDs, alcance rápido/habitual/completo, extracción,
enriquecimiento y fragmentos para permutaciones. Se puede iniciar una
investigación solo con un ID. El plan llega a los motores tradicional,
agéntico e híbrido y queda guardado en `target.extra_data.maigret_plan`.
Los IDs se guardan en `target.extra_data.identifiers`; no requieren migración.

```json
{
  "target": {
    "identifiers": [{"value": "0000-0002-1825-0097", "id_type": "orcid"}]
  },
  "strategy": "rule_based",
  "maigret_plan": {
    "scan_mode": "all",
    "options": {"parse": true, "enrich": true}
  }
}
```

Los IDs encontrados conservan tipo y fuentes. Los alias admiten Unicode y
mantienen el filtro de roles. Un ID numérico tipado no se convierte en username.
Una lista adicional conserva namespaces aunque dos IDs tengan el mismo valor.
ORCID valida su dígito de control y el control inventado también lo respeta.
Los IDs opacos sensibles a mayúsculas se mantienen separados al deduplicar.

Las URLs generadas o sin datos no crean menciones ni cuentas. Sus identificadores
derivados se conservan como candidatos en el runtime. Una extracción de contenido
registra una observación de página; no atribuye identidad.

## MCP y llamadas dirigidas

`fast` limita el prefijo; `deep` respeta el límite configurado; `all` extiende al
catálogo completo. Ampliar cobertura no repite el prefijo compatible. Cambiar
recetas, extractores, transportes u opciones invalida la caché correspondiente.
La selección explícita de una receta sobrevive a la deduplicación por host.

```json
{
  "tool_name": "username_finder",
  "inputs": {
    "username": "alias",
    "scan_mode": "all",
    "maigret_options": {
      "names": ["GitHub", "GitHubGist"],
      "keywords": ["universidad"],
      "parse": true,
      "enrich": true,
      "retries": 1,
      "permutation_parts": ["nombre", "apellido"]
    }
  }
}
```

```json
{
  "tool_name": "maigret_enricher",
  "inputs": {
    "identifiers": [{"value": "76561198012345678", "id_type": "steam_id"}],
    "candidate_urls": ["https://github.com/alias"],
    "maigret_options": {"tags": ["gaming"], "enrich": true}
  }
}
```

También se admite `excluded` para excluir etiquetas. Las llamadas no aceptan
cookies, proxies, endpoints ni rutas del servidor. El contexto MCP muestra
fuentes de IDs, intentos, cobertura, diagnósticos y presupuestos efectivos.

## Transporte y coexistencia

Las solicitudes normales, activaciones y postprocesadores síncronos pasan por
JSONL al padre; el worker no abre sockets de red propios. El puente elimina las
cabeceras de compresión de cuerpos ya decodificados. Maigret y WhatsMyName
comparten una cuota; la rama complementaria deja espacio durante el arranque
del worker. El check tiene margen para la cola y el enriquecimiento, mientras
cada petición conserva su timeout y los límites global y por host. La
cancelación termina el proceso y libera sus consultas.

Cada redirección curl se valida. Los proxies públicos se conectan a una IP
validada conservando Host/TLS. Tor/I2P se limitan al catálogo y requieren su
gateway; una consulta pública de una receta Tor conserva ese gateway. No se
sustituye por acceso directo cuando falta configuración.

El solver es un servicio administrado y de confianza, potencialmente local.
Se valida el destino antes de enviarlo y la URL final de su respuesta. Su red,
DNS y redirecciones internas pertenecen al servicio y necesitan aislamiento
de salida propio. Sus checks tienen plazo y concurrencia separados. Cookies
marcan `access_context=configured_session`; sin ellas se marca `anonymous`.
Diagnósticos y huellas omiten credenciales y rutas, usando tipos de error,
hashes y flags de configuración.

Los especialistas siguen registrados y sus evidencias se fusionan.
`social_verifier` reconoce recetas e IDs sin depender de los filtros del barrido;
`domain_finder` conserva su catálogo amplio de proveedores. Ambas herramientas
Maigret se excluyen de relaciones inducidas solo por una semilla de enumeración.
Disqus conserva su probe API y corrige la URL pública a `/by/{username}/`.
Telegram mantiene el parser de peers y no toma el contacto genérico como prueba.

## Configuración

| Variable | Predeterminado | Función |
|---|---:|---|
| `USERNAME_SCAN_MAX_SITES` | `3400` | Límite habitual; cero activa todo |
| `USERNAME_SCAN_MAX_ALIASES` | `3` | Usuarios por investigación |
| `MAIGRET_PARSE` / `MAIGRET_ENRICH` | `true` | Extracción y consultas secundarias |
| `MAIGRET_RETRIES` | `1` | Reintentos, entre cero y cinco |
| `MAIGRET_REQUEST_TIMEOUT` | `10` | Plazo HTTP, segundos |
| `MAIGRET_WORKER_TIMEOUT` | `900` | Plazo de proceso, segundos |
| `MAIGRET_TOOL_TIMEOUT` | `1800` | Plazo de herramienta MCP, segundos |
| `MAIGRET_QUEUE_GRACE` | `30` | Margen del check para cola y enriquecimiento |
| `MAIGRET_MAX_IDENTIFIERS` | `10` | IDs consultados por investigación |
| `MAIGRET_MAX_PARSE_URLS` | `10` | URLs adicionales intentadas por el enriquecedor |
| `MAIGRET_MAX_PERMUTATIONS` | `10` | Variantes; sigue aplicando el límite de alias |
| `MAIGRET_TAGS`, `MAIGRET_SITE_NAMES`, `MAIGRET_EXCLUDED_TAGS`, `MAIGRET_KEYWORDS` | `[]` | Listas JSON |
| `MAIGRET_COOKIE_FILE` | Vacío | Archivo Netscape del servidor |
| `MAIGRET_PROXY`, `MAIGRET_TOR_PROXY`, `MAIGRET_I2P_PROXY` | Vacío | Gateways administrados |
| `MAIGRET_SOLVER_URL` | Vacío | Endpoint JSON de FlareSolverr |
| `MAIGRET_SOLVER_TIMEOUT` / `MAIGRET_SOLVER_CONCURRENCY` | `65` / `4` | Presupuesto del solver |
| `MAIGRET_CHECK_DOMAINS` | `false` | Checks DNS, sin atribuir propiedad |
| `MAIGRET_DATABASE_FILE` | Vacío | Snapshot propio; reiniciar al cambiarlo |

Se registran `username_scan_engine_version=4`, `maigret_enricher_version=1`,
versión, SHA-256 y opciones. Si la base cambia durante el arranque o después
de cachearse, el proceso falla y pide recargar, sin mezclar versiones.

## Informes y mantenimiento

El menú del expediente ofrece los formatos disponibles. Por HTTP:

```text
GET /api/v1/investigations/UUID/maigret/report?format=pdf
GET /api/v1/investigations/UUID/maigret/report?format=csv
```

MCP `get_maigret_report` devuelve formato, tamaño, descarga y un extracto
acotado de texto. No ejecuta otra búsqueda. Los escritores originales reciben
checks guardados y detecciones enriquecidas. JSON/NDJSON filtran positivos
como upstream; CSV conserva también errores y ausencia de detección. Los
rechazos de Person Map se exportan inconclusos y no reaparecen como positivos.

Los informes indican que no atribuyen pertenencia. El grafo nativo y Neo4j
representan enlaces e IDs; el grafo de identidad y GraphML siguen independientes.
PDF no carga imágenes remotas ni archivos indicados por un perfil. HTML/grafo
llevan política de contenido y se sirven como adjuntos. Los temporales se
eliminan y cada exportación se limita a 10 MiB.

Desde `backend`:

```bash
.venv/bin/python scripts/maigret_catalog.py info
.venv/bin/python scripts/maigret_catalog.py list --id-type orcid
.venv/bin/python scripts/maigret_catalog.py check --sites GitHub Disqus --output ../docs/experiments/maigret-check.json
.venv/bin/python scripts/maigret_catalog.py update --ref v0.6.6 --output app/tools/data/maigret-v0.6.6.json
```

La actualización exige tag de versión o commit completo, crea un archivo nuevo
y guarda procedencia. No sobrescribe ni activa la base. El self-check usa
controles originales sin desactivar sitios ni escribir cambios en el snapshot.

## Validación

Las suites Maigret ejecutan el worker real contra respuestas controladas:
extracción API, POST, herencia, controles, namespaces, ORCID, Unicode, cookies,
proxies, redirecciones, solver, DNS, cobertura, cancelación, auditoría y diez
formatos. La suite general y las pruebas PostgreSQL cubren especialistas,
trazabilidad, deduplicación y MCP.

La primera integración está documentada en [el ensayo inicial](experiments/2026-10-13-maigret-live.md).
La ampliación y el ensayo tradicional real están en
[la validación de capacidades](experiments/2026-10-13-maigret-expanded-live.md).

Fuentes: [Maigret](https://github.com/soxoj/maigret),
[uso como biblioteca](https://maigret.readthedocs.io/en/latest/library-usage.html),
[socid-extractor](https://github.com/soxoj/socid-extractor).
