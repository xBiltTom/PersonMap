# Motor de búsqueda pública

El coordinador ejecuta cada consulta con Tavily → TinyFish Search → DuckDuckGo.
Un motor se usa solo si está disponible. Si devuelve un error, una respuesta
inválida o ningún resultado que pase los filtros locales, se intenta el
siguiente **para esa consulta**, aunque otra consulta ya haya encontrado algo.

## Configuración

```dotenv
TAVILY_API_KEY=
TAVILY_SEARCH_DEPTH=basic
TAVILY_MAX_QUERIES=5
TAVILY_MAX_RESULTS=8
TAVILY_EXACT_MATCH=true
TAVILY_REQUIRE_LITERAL_MATCH=true
SEARCH_MAX_QUERIES_PER_ROUND=5
SEARCH_TIMEOUT_SECONDS=90
TINYFISH_API_KEY=
TINYFISH_LOCATION=PE
TINYFISH_LANGUAGE=es
SEARCH_READ_PAGES=false
SEARCH_MAX_PAGES=2
TINYFISH_FETCH_ENABLED=false
```

TinyFish no exige instalar un SDK: se utiliza HTTP con `X-API-Key`. Una clave
vacía o ausente omite completamente este proveedor. Si falta también Tavily,
se intenta DuckDuckGo. Una clave inválida, cuota agotada, límite de frecuencia,
timeout o error del proveedor tampoco elimina los hallazgos ya recogidos.
Esto garantiza continuidad del coordinador, no disponibilidad de las fuentes:
si todos los proveedores fallan, no se inventan resultados.

`TAVILY_MAX_QUERIES` conserva su nombre por compatibilidad, pero limita las
consultas distintas durante **toda la investigación**, incluyendo rondas de
pivoteo. Cada proveedor tiene además un contador compartido de intentos con ese
mismo límite. No hay reintentos automáticos ni redirecciones de las APIs
con credenciales. Los códigos 401/402/403/429/432 deshabilitan ese motor durante
el resto de la investigación; los errores 5xx permiten probarlo con la siguiente
consulta. El timeout del coordinador se aplica a cada ejecución de la herramienta.

Con cinco consultas y profundidad básica, Tavily puede consumir hasta cinco
créditos; `advanced` puede consumir hasta diez. Los respaldos tienen sus propias
cuotas y tarifas. El campo `usage.credits` se conserva cuando Tavily lo proporciona;
no se confunde una respuesta vacía con una consulta gratuita.

Para dejar capacidad a nuevos identificadores después de la primera ronda,
configura, por ejemplo, `TAVILY_MAX_QUERIES=8` y
`SEARCH_MAX_QUERIES_PER_ROUND=5`. Los valores predeterminados mantienen el límite
anterior de cinco. Una investigación con suficientes identificadores iniciales
puede agotar ese límite y no consultar los pivotes posteriores.

## Selección y comprobación

Se alternan las clases de identificadores: correo, teléfono, DNI, alias y nombre,
antes de gastar espacio en teléfonos adicionales o consultas limitadas a redes.
Los correos y alias descubiertos también generan consultas; los nombres candidatos
se usan si falta un nombre inicial. Se acotan los candidatos y las consultas
ya ejecutadas no se repiten.

El filtro local compara identificadores completos y conserva letras Unicode.
Tolera tildes y mayúsculas, pero rechaza `ana` dentro de `banana`, un correo dentro
de otro y un alias presente solamente en los parámetros de una URL. Un segmento
completo de ruta puede apoyar una coincidencia de nombre/alias, incluyendo
`juan-perez`; no se concatenan palabras arbitrarias. DNI y teléfono siempre
requieren coincidencia en título o extracto, incluso al desactivar el filtro general.

Tavily recibe `exact_match` configurable e `include_usage`; en consultas de teléfono
se desactiva la coincidencia nativa para mantener las variantes unidas por OR.
Los dominios se restringen en la API y se vuelven a comprobar localmente en los
**tres** motores. Las URLs inválidas, con credenciales, destinos locales/IP privadas
o rutas de proveedores privados de DNI se excluyen. Cada registro malformado
se descarta sin perder los registros válidos del mismo lote.

Las URLs aceptadas se deduplican entre rondas. Una coincidencia válida ya vista
satisface la consulta y evita activar innecesariamente otro proveedor.
`confidence` prioriza hallazgos; no demuestra que una cuenta o mención pertenezca
al objetivo. Se conserva `ownership_status=unverified`.

## Lectura adicional de páginas

`SEARCH_READ_PAGES=true` activa la lectura de hasta dos páginas web generales por
investigación. Es opcional para controlar solicitudes y latencia. Redes sociales
y documentos DNI mantienen sus verificadores específicos, incluido OCR local.

El lector nativo admite HTML/texto público, elimina scripts y elementos de navegación,
limita cada respuesta a 1 MB y el texto a 20 000 caracteres. Revisa cada redirección,
aplica el transporte con comprobación de DNS público y rechaza páginas de acceso.
No inicia sesión. Una coincidencia en el texto añade un extracto y la URL final como
evidencia; no aumenta la confianza ni convierte otros nombres/correos del artículo
en identidades del objetivo. Si el texto no confirma los términos, queda registrado
`page_literal_match=false` y se mantiene únicamente la mención del buscador.

TinyFetch requiere **clave y ambos flags**:

```dotenv
SEARCH_READ_PAGES=true
TINYFISH_API_KEY=tu_clave
TINYFISH_FETCH_ENABLED=true
```

Se usa cuando la lectura nativa falla o devuelve poco contenido, por ejemplo una
página que depende de JavaScript. No se activa ante una página de login, destino
inseguro, documento no admitido o respuesta demasiado grande. Se comprueban
`errors[]`, la URL solicitada y la URL final, incluso ante HTTP 200. Sus límites
de timeout, tamaño, páginas y cuota evitan peticiones repetidas. Sin clave, el
lector nativo sigue funcionando; un fallo de TinyFetch conserva el hallazgo inicial.
TinyFetch no sustituye el OCR de PDF escaneados. TinyAgent no se invoca.

## Diagnósticos y validación

`context.extra.search_diagnostics` registra proveedor, consulta, estado,
hallazgos aceptados y créditos declarados, sin guardar claves ni respuestas de error
completas. Aparece también en los metadatos de los hallazgos, en el evento
`tool_complete` de reglas y en los resultados de herramientas enviados al agente.
`search_provider_attempts`, `search_disabled_backends` y `search_read_urls`
permiten revisar los presupuestos. La huella de ejecución incluye la versión 2
del buscador y sus ajustes, sin claves.

Las pruebas locales usan HTTP simulado e incluyen respaldo parcial, ausencia de
claves, respuestas inválidas, errores y cuota de TinyFish, Unicode, filtros de
dominio, URLs, redirecciones, lectura, límites y presupuestos entre rondas.
La suite completa terminó con **456 pruebas aprobadas y 3 excluidas** por requerir
red o PostgreSQL. Además, dos consultas reales a Tavily consumieron un crédito
básico cada una: la consulta general conservó siete coincidencias y la restringida
a `docs.tavily.com` no produjo coincidencias aceptadas. Registro:
[search-2026-10-07-implementation-live.json](audits/search-2026-10-07-implementation-live.json).

La disponibilidad real de TinyFish requiere configurar una clave y comprobarla;
las pruebas simuladas no demuestran su cobertura real.

Referencias de contratos oficiales:
[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[TinyFish Search](https://docs.tinyfish.ai/search-api/reference),
[TinyFish Fetch](https://docs.tinyfish.ai/fetch-api/reference).
