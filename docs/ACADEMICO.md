# Motor académico: OpenAlex, Crossref y perfiles públicos

`academic_finder` versión 3 combina consultas independientes a Crossref y
OpenAlex. Conserva el nombre del tool, los tipos de entidades y la integración
en reglas, agente, híbrido y MCP. Scholar sigue en `google_account_osint` y su
lectura de perfiles no depende de estas APIs. GHunt y Maigret conservan sus
entornos y coberturas. No hay dependencias ni migraciones nuevas.

## Entradas y recuperación

| Entrada | Crossref | OpenAlex | Comprobación local |
| --- | --- | --- | --- |
| Nombre completo | `works?query.author=...`; afiliación contextual opcional | Candidatos en `authors`, obras por `author.id` | Nombre completo/variantes de orden; ID del autor en cada obra |
| ORCID | `works?filter=orcid:...` | Autor filtrado por ORCID y sus obras | Host, formato, checksum y ORCID observado; ID de autor contrastado |
| URL DOI | Registro `works/{doi}` | Obras filtradas por DOI | DOI de la respuesta igual al solicitado |

Las fuentes se consultan por separado: OpenAlex sin candidatos, bloqueado o
sin clave no impide aprovechar Crossref. La consulta de afiliación de Crossref
puede repetirse sin ese campo si no aporta coincidencias válidas: los metadatos
editoriales pueden omitirla. No se expanden iniciales ni se acepta el primer
resultado por ranking. Se admite la búsqueda por apellidos/nombres conforme a
las variantes del motor y los campos `given`/`family` de Crossref.

La afiliación se contrasta en el **autor coincidente**, no en cualquier coautor.
Se conserva como señal `affiliation_match=true/false/null`; una diferencia
puede corresponder a una afiliación anterior y no prueba que sea otra persona.
Los homónimos y los autores de OpenAlex permanecen candidatos:
`ownership_status=unverified`.

Una consulta DOI sin nombre/ORCID recupera la publicación con
`target_association_status=not_asserted`. Sus coautores no se convierten en
identidades ni pivotes del objetivo. Solo los ORCID del autor coincidente se
exponen como enlaces para continuar una búsqueda; siguen conservando su origen
y condición de candidatos. Las iniciales, variantes no reconocidas y metadatos
ausentes siguen siendo huecos deliberados de cobertura.

## Unificación y procedencia

Los DOI se normalizan desde su forma textual y los hosts `doi.org`/`dx.doi.org`
a una URL canónica. La persistencia reconoce esa misma clave en observaciones
anteriores y evita publicaciones duplicadas por mayúsculas o protocolo.
Se rechazan hosts parecidos, credenciales en URLs, espacios, controles y rutas
de navegación. No se solicita la URL proporcionada por el objetivo: se consultan
los endpoints fijos de las APIs usando el identificador validado.

Cada publicación conserva `academic_sources` y `academic_records`: proveedor,
URL de evidencia, autores, coincidencias y afiliaciones observadas. Se guardan
los conteos de citas bajo `citation_counts.crossref` y `.openalex`, **sin
sumarlos**. Las consultas posteriores por DOI conservan la evidencia de autoría
observada antes; no la sustituyen por una afirmación de identidad.

OpenAlex [incorpora datos de Crossref](https://help.openalex.org/data/how-its-built/).
La coincidencia entre ambos no se interpreta como dos confirmaciones
independientes de identidad. La herramienta conserva una sola procedencia de
recolección (`academic_finder`) y declara el solapamiento de metadatos.

Se conservan editorial, revista, año, enlaces y actualizaciones de publicaciones
cuando están disponibles. OpenAlex aporta ubicaciones y URLs PDF únicamente
si las declara abiertas. Los enlaces de texto completo de Crossref no se
presentan automáticamente como acceso abierto y no se descargan en este tool.
El indicador de retractación de OpenAlex y los registros de actualización de
Crossref conservan su procedencia; no son un dictamen sobre el trabajo.

## Límites, fallos y continuidad

| Variable | Predeterminado | Alcance |
| --- | --- | --- |
| `CROSSREF_ENABLED` | `true` | Activa la fuente pública Crossref |
| `CROSSREF_MAILTO` | vacío | Contacto opcional del operador; nunca se rellena con el correo investigado |
| `OPENALEX_API_KEY` | vacío | Credencial opcional; se envía solo a OpenAlex y no se guarda en resultados |
| `ACADEMIC_MAX_NAMES` | `3` | Nombres por investigación |
| `ACADEMIC_MAX_ORCIDS` | `3` | ORCID por investigación |
| `ACADEMIC_MAX_DOIS` | `3` | DOI por investigación |
| `ACADEMIC_MAX_REQUESTS` | `24` | Intentos acumulados por investigación, entre ambas APIs |
| `ACADEMIC_RESULTS_PER_QUERY` | `10` | Primera página de resultados de cada consulta |
| `ACADEMIC_REQUEST_TIMEOUT` | `8` | Segundos por petición, sin reintentos automáticos |
| `ACADEMIC_BATCH_TIMEOUT` | `60` | Segundos por lote; conserva hallazgos ya completados |

Los valores se acotan también en el código. Se admiten hasta tres autores
candidatos de OpenAlex por consulta. Crossref se serializa entre investigaciones
del mismo proceso y respeta un máximo de cinco peticiones por segundo, además
de los presupuestos HTTP globales. Los límites no coordinan procesos diferentes.

401/403/429 suspenden ese proveedor para esa investigación hasta un refresco
explícito. Los errores, respuestas incompatibles, resultados vacíos y límites
agotados se distinguen en diagnósticos. No significan ausencia de publicaciones.
La cobertura es intentada y acotada, no exhaustiva. Cambiar configuración invalida
solo las cachés académicas. Los límites y consultas sobreviven a la recarga
desde PostgreSQL; la configuración forma parte de la huella de ejecución.

## MCP y modo tradicional

El barrido tradicional usa nombres y ORCID del objetivo y los pivotes observados
en rondas posteriores, respetando la cobertura acumulada. MCP y los agentes
también admiten subconsultas explícitas. Ejemplos de `inputs` para `academic_finder`:

```json
{"full_name": "Nombre Apellidos", "university": "Universidad observada"}
```

```json
{"identifiers": [{"id_type": "orcid", "value": "0000-0002-1825-0097"}]}
```

```json
{"candidate_urls": ["https://doi.org/10.7717/peerj.4375"]}
```

MCP requiere además los identificadores habituales de expediente y sesión.
Una entrada explícita selecciona su alcance y no dispara todos los nombres y
DOI heredados. Las llamadas idénticas reutilizan su ejecución; `force` permite
repetir y refresca solo esta herramienta. El contexto expone `academic` con
capacidades, consultas, diagnósticos e intentos. Trazas y consola muestran los
estados aunque no se produzcan hallazgos.

## Verificación

```bash
cd backend
.venv/bin/pytest tests/test_academic_engine.py tests/test_academic_evidence.py -q
.venv/bin/pytest tests/test_mcp_workspace_db.py -m db -q
.venv/bin/python scripts/academic_audit.py --doi 10.7717/peerj.4375 --output /tmp/academic-audit.json
```

La [prueba en vivo del 2026-10-15](experiments/2026-10-15-academic-live.json)
consultó el DOI público `10.7717/peerj.4375`: ambas APIs respondieron HTTP 200,
se obtuvo una sola publicación y se conservaron los conteos de citas separados.
No usa la BD, correo ni sesión del operador; no prueba asociación personal.
La [prueba adicional por ORCID](experiments/2026-10-15-academic-orcid-live.json)
seleccionó un ORCID publicado en los metadatos de ese artículo. Crossref y las
dos consultas de OpenAlex respondieron HTTP 200: un perfil de autor y once
publicaciones en las páginas acotadas consultadas, con asociación personal
sin verificar. Este ensayo tampoco usa datos del operador ni confirma que
la lista sea exhaustiva.

Los recorridos por nombre, homónimos, afiliaciones de coautores, fallos,
presupuestos, concurrencia y continuación del barrido se verifican además con
HTTP controlado. Las pruebas MCP/PostgreSQL usan esquemas temporales.
La suite general completó **827 pruebas**, y las **13 pruebas PostgreSQL**
también pasaron. Las comprobaciones finales de metadatos y huella de
configuración se ejecutaron aparte tras la suite general.

Referencias oficiales: [API y metadatos de Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/),
[filtros](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/)
y [acceso y límites](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/).
La integración implementa sus contratos HTTP; no instala ni ejecuta un paquete
de terceros ni incorpora textos completos o abstracts de las publicaciones.
