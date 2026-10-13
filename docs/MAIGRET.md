# Integración de Maigret

`username_finder` ejecuta **Maigret 0.6.6 completo como biblioteca**, en un
proceso Python por alias. Conserva su nombre público en el registry, REST, MCP
y el agente. WhatsMyName aporta únicamente las plataformas sin una receta
equivalente de Maigret. GitHub, Keybase, Wikipedia, Gravatar y las demás fuentes
especializadas conservan sus funciones.

## Ejecución

1. `maigret_catalog.py` lee el catálogo incluido en la distribución fijada en
   `uv.lock`. Prioriza las plataformas conocidas y elimina consultas duplicadas
   por plataforma. Los datasets originales siguen separados.
2. `maigret_worker.py` carga `MaigretDatabase` y llama a `maigret.search`, con
   extracción y enriquecimiento. Upstream ejecuta herencia de motores,
   `urlProbe`, métodos, cabeceras, cuerpos, activaciones, detección, extracción,
   mutaciones y reintentos.
3. El worker delega sus consultas por JSONL a `maigret_runner.py`. Las consultas
   normales, las activaciones y los postprocesadores síncronos utilizan el
   transporte HTTP de Person Map. `curl_cffi` conserva la emulación TLS del
   navegador, con el mismo presupuesto global y por host, verificación de
   certificados y DNS público fijado; cada redirección se valida por separado.
   Los barridos nativo y complementario comparten también una única cuota de
   concurrencia de `username_finder`, respetando el presupuesto de las otras
   herramientas. El puente elimina las cabeceras de compresión y encuadre al
   trasladar cuerpos que el cliente ya descomprimió.
4. Para cada detección positiva se ejecuta un control negativo con la misma
   receta nativa. Una plataforma que también encuentra ese alias se descarta;
   un control bloqueado o fallido queda inconcluso. Telegram conserva su parser
   de peers: la plantilla genérica de contacto no prueba existencia ni ausencia.
   Disqus conserva su consulta API original y corrige únicamente la URL pública
   a `/by/{username}/`, que también reconoce el normalizador de perfiles.
5. Los resultados se convierten a `ToolFinding` con datos extraídos, enlaces,
   identificadores tipados y URLs de evidencia. Continúan siendo candidatos;
   `social_verifier` mantiene la verificación especializada y los especialistas
   añaden sus evidencias. La detección de una cuenta no atribuye su pertenencia.

El proceso separado permite adaptar el transporte sin modificar los módulos
de Maigret cargados por otras herramientas. Las importaciones de su CLI y sus
objetos mutables quedan confinadas al worker. El proceso se termina y se
liberan las consultas pendientes al cancelar la herramienta o agotar su plazo.
Un fallo del worker se registra como fallo; no cambia silenciosamente de motor.

## Configuración

| Variable | Valor predeterminado | Función |
|---|---|---|
| `USERNAME_SCAN_MAX_SITES` | `3400` | Máximo de plataformas por alias; el entorno puede sobrescribirlo |
| `USERNAME_SCAN_MAX_ALIASES` | `3` | Presupuesto de alias por investigación |
| `MAIGRET_ENRICH` | `true` | Consultas secundarias para ampliar los datos extraídos |
| `MAIGRET_REQUEST_TIMEOUT` | `10` | Plazo de petición nativa, en segundos |
| `MAIGRET_WORKER_TIMEOUT` | `900` | Plazo total por worker, en segundos |
| `MAIGRET_TAGS` | `[]` | Etiquetas de sitios; lista JSON |
| `MAIGRET_SITE_NAMES` | `[]` | Nombres de sitios seleccionados; lista JSON |
| `MAIGRET_EXCLUDED_TAGS` | `[]` | Etiquetas excluidas; lista JSON |
| `MAIGRET_KEYWORDS` | `[]` | Palabras que Maigret busca en las páginas |

Por ejemplo, `MAIGRET_SITE_NAMES=["GitHub","Reddit","Telegram"]` restringe
el barrido. La selección no impide a `social_verifier` reconocer perfiles de
otras plataformas ni hace que `domain_finder` las considere dominios personales.

El catálogo de la distribución fijada contiene 5.897 entradas. Con los filtros
operacionales y la deduplicación se obtienen **5.401 plataformas: 5.103 con motor
Maigret y 298 complementarias de WhatsMyName**. Con un límite de 500, la selección
actual incluye 291 recetas nativas y 209 complementarias. Estas cifras describen
el catálogo, no garantizan que todos los sitios sean accesibles o extraíbles.

La integración actual busca alias en la web pública. Conserva los otros
identificadores descubiertos en `discovered_identifiers`, sin convertir IDs
numéricos en aliases. Tor/I2P, búsqueda por otros tipos de identificador, el
servidor web propio, los reportes propios y el modo IA del CLI no se activan
desde esta herramienta: necesitan configuración o contratos adicionales y
varios duplican funciones de Person Map. Las protecciones que necesitan un
solver externo pueden producir consultas inconclusas; la emulación TLS por
`curl_cffi` sí está integrada.

## Compatibilidad y reproducibilidad

- El `source_tool` sigue siendo `username_finder`; el motor figura como
  `search_engine=maigret`. Esto conserva la exclusión de aristas inducidas por
  compartir el alias utilizado como semilla.
- Las URLs equivalentes de proveedores conocidos se normalizan antes de
  deduplicar. Se conservan los metadatos y fuentes de los especialistas.
- La cobertura rápida se puede ampliar a profunda sin repetir el prefijo.
  Cambiar versión, catálogo u opciones invalida la cobertura incompatible.
- Se registra `username_scan_engine_version=3`, versión de Maigret y SHA-256
  de su catálogo. No se descarga una base cambiante durante la investigación.
- El antiguo snapshot y adaptador permanecen como referencia para las
  mediciones anteriores; el barrido actual utiliza el catálogo nativo fijado.

## Comparación reproducible

`backend/tests/test_maigret_integration.py` ejecuta el worker real contra
respuestas simuladas y compara las mismas respuestas con el comprobador anterior:

| Caso | Comprobador anterior | Maigret integrado |
|---|---|---|
| Perfil de GitHub mediante API | Detecta la cuenta | Detecta la misma cuenta y extrae bio, avatar y alias; consulta enlaces sociales |
| Receta con herencia, endpoint de prueba y POST | No ejecuta la receta completa | Detecta la cuenta y valida el control con la misma receta |
| Sitio que responde positivo a cualquier alias | El control permite rechazarlo | Se rechaza mediante control nativo |
| Plataforma exclusiva de WhatsMyName | Disponible | Se mantiene sin un segundo barrido completo |

También se verifican extracción síncrona, cancelación del proceso, destinos
privados en redirecciones del navegador, actualización de cobertura y fusión
con evidencias de otros especialistas. Estas pruebas demuestran capacidades y
contratos de integración; no son una medición de precisión o latencia sobre
sitios reales. Los límites configurados y la accesibilidad externa siguen
determinando los resultados de cada investigación.

La validación con un registro exitoso de la base y el orquestador tradicional
real se documenta en [el ensayo del 13 de octubre de 2026](experiments/2026-10-13-maigret-live.md).
Para repetirla en una investigación nueva, desde `backend`:

```bash
.venv/bin/python scripts/validate_maigret_live.py run --source UUID_DE_INVESTIGACION --output ../docs/experiments/maigret-live.json
```

El script reutiliza los campos y el consentimiento almacenado del objetivo,
desactiva la IA únicamente en ese proceso y conserva la investigación original.
El informe recoge URLs públicas, métricas, controles y estados de herramientas;
omite los datos de contacto y el contenido de exposiciones.

Fuentes: [Maigret](https://github.com/soxoj/maigret),
[uso como biblioteca](https://maigret.readthedocs.io/en/latest/library-usage.html),
[socid-extractor](https://github.com/soxoj/socid-extractor).
