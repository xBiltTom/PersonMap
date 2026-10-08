# Auditoría de búsqueda por DNI — 2026-10-07

## Resultado

El motor puede consultar un proveedor y buscar el DNI entrecomillado en la web,
pero todavía no permite distinguir con suficiente rigor un documento aportado,
una mención pública y una identidad corroborada. Hay errores reproducibles de
validación, asociación y procedencia. No se modificó el código de la aplicación
durante esta revisión.

## Recorrido actual

- `DniLookupTool` elimina todo lo que no sea un dígito y exige ocho caracteres
  resultantes. Consulta apis.net.pe v2 si hay token, o v1 si no hay token.
  Después intenta APIsPERU si no obtuvo un nombre.
- Solo usa nombres y apellidos de la respuesta. Produce una entidad `document`
  con plataforma `reniec_peru`, confianza 0,99 si tiene algún nombre/apellido y
  0,85 si todos los proveedores fallan. No conserva URLs de evidencia.
- `SearchDorkerTool` genera una consulta general `"<dni>"`, sobre Tavily con
  respaldo DuckDuckGo. Analiza títulos, extractos y URLs; no descarga ni valida
  el contenido íntegro de los documentos encontrados.
- El formulario limita la entrada, pero `TargetCreate` no valida el formato del
  DNI. La API y las llamadas de herramientas permiten eludir el formulario.

## Problemas prioritarios

### 1. Un fallo de proveedor produce un hallazgo con confianza elevada

Con ambos proveedores respondiendo 503, se obtiene `DNI 12345678`, fuente
`format_validated`, confianza 0,85 y ninguna evidencia. Ese resultado solo
repite la entrada y comprueba su longitud; no demuestra existencia, titularidad
ni una consulta exitosa. La confianza es una prioridad interna del sistema,
no una probabilidad calibrada de identidad.

**Mejora:** distinguir `input_only`, `format_valid`, `provider_reported`,
`public_mention` y `corroborated`. Conservar diagnósticos de ausencia de clave,
fallo HTTP, respuesta inválida y ausencia de datos. El formato correcto no
debe presentarse como un hallazgo corroborado.

### 2. Se acepta la respuesta de otra persona o un cuerpo de error

Una respuesta 200 con `numeroDocumento: 87654321` al consultar `12345678`
produce un nombre con confianza 0,99. Ocurre lo mismo con `success: false`
si el cuerpo incluye `nombres`. Un apellido aislado también se considera una
consulta exitosa. No hay validación de tipos ni del contrato de cada proveedor.

**Mejora:** adaptadores por proveedor con validación de éxito, esquema, nombres
y documento devuelto. Rechazar discrepancias; si falta el documento, reflejar
la falta de confirmación en lugar de asumir igualdad. Conservar proveedor,
fecha, endpoint sin credenciales y campos efectivamente reportados.

### 3. La búsqueda web acepta coincidencias numéricas parciales

La comparación literal genérica acepta `991234567899` para `12345678`,
ensambla `12 34 56 78` y acepta una URL `?q=12345678` aunque título y extracto
no contengan el documento. Desactivar el filtro literal también permite
resultados meramente semánticos para el DNI.

**Mejora:** comparador específico de documentos, límites numéricos estrictos,
contexto DNI/documento cuando haga falta y comprobación obligatoria del título
o texto observado. La URL por sí sola no confirma una mención documental.
Separar la mención del DNI de su asociación con una persona; una tabla pública
puede incluir muchos nombres y documentos.

### 4. Los proveedores y su autenticación necesitan actualización

[apis.net.pe](https://apis.net.pe/) anuncia que migró sus APIs a Decolecta,
mientras el motor conserva sus endpoints antiguos. La
[documentación enlazada por el proveedor](https://decolecta.gitbook.io/docs)
establece la nueva base y autenticación Bearer. Esto justifica revisar el
adaptador, pero no demuestra que cada endpoint antiguo esté caído.

[APIsPERU](https://apisperu.com/servicios/dniruc) pide registro y token para
consultar; el respaldo actual no envía credenciales ni tiene una configuración
para ellas. Ninguno de los dos dominios consultados es un endpoint de RENIEC,
aunque la descripción diga «portales públicos gubernamentales» y la plataforma
guardada sea `reniec_peru`. La documentación del código anuncia tres capas,
pero con token intenta v2 y después APIsPERU: no pasa antes por v1.

**Mejora:** habilitar proveedores documentados con sus propias credenciales,
describirlos como terceros, fijar una política explícita de respaldo y estados
de disponibilidad. Limitar llamadas y reintentos y conservar una caché por
investigación. Mantener las búsquedas públicas disponibles sin credenciales.

### 5. El nombre obtenido no alimenta las siguientes búsquedas heurísticas

El hallazgo conserva `metadata.full_name`, pero `extract_and_apply_pivots` no
lo incorpora a `context.full_name` ni a `discovered_names`. Una investigación
de reglas iniciada solo con DNI no pasa automáticamente a buscar por ese
nombre. Los modos con LLM pueden usarlo manualmente, sin una garantía común.

**Mejora:** conservar nombres candidatos con procedencia y nivel de verificación,
procesarlos en todos los motores y ajustar claves de ejecución y presupuestos.
Resolver conflictos con un nombre aportado sin reemplazarlo silenciosamente.
El nombre obtenido debe habilitar búsquedas, no confirmar todos los perfiles
homónimos que devuelvan.

### 6. Validación y presentación incompletas

`abc12345678xyz` activa el lookup porque se eliminan las letras; el buscador
utiliza la entrada original, por lo que ambas herramientas pueden investigar
valores distintos. Se aceptan dígitos Unicode. El esquema de entrada acepta
hasta nueve dígitos sin diagnóstico. `_extract_full_name` pierde `segundoNombre`
cuando existe `primerNombre`. La descripción menciona RUC, pero el motor solo
acepta ocho dígitos y no implementa consultas RUC. El nodo raíz de una búsqueda
solo por DNI mantiene el título genérico «Identidad Objetivo».

**Mejora:** normalización común y validación de ocho dígitos ASCII en API y
herramientas, conservando ceros iniciales. Combinar correctamente nombres
separados, mostrar el DNI en la raíz y exponer al usuario los estados del lookup.
Tratar RUC como una capacidad independiente si se implementa.

## Verificación

Se ejecutaron las pruebas existentes de lookup DNI, esquemas y buscador:
**27 aprobadas**. Estas pruebas simulan HTTP y no cubren las discrepancias
documentales ni los falsos positivos anteriores.

Además se reprodujeron los casos de esta auditoría con números y nombres
sintéticos, sin consultar titulares reales. Los resultados están en
[el registro JSON](audits/dni-2026-10-07-code.json). No se comprobó disponibilidad
real de los endpoints de lookup ni se usaron credenciales del proyecto.

Antes de considerar el motor óptimo, conviene cubrir discrepancia de documento,
errores con HTTP 200, respuestas incompletas/malformadas, entradas inválidas,
ceros iniciales, coincidencias parciales/reflejadas en URL, fallos de proveedor,
autenticación, deduplicación y búsquedas posteriores por nombre con conflictos.

## Implementación posterior: evidencia pública

Tras acordar el alcance OSINT, se sustituyó el lookup de mirrors por la lectura
de publicaciones abiertas. RENIEC sigue incluido como publicador: el buscador
genera una consulta específica para `reniec.gob.pe`, además de la consulta
general y otra de documentos/datos abiertos institucionales. Esto no presupone
que exista un dataset público con DNI completos para cualquier proceso electoral.

El comparador de DNI exige ocho dígitos ASCII, conserva ceros iniciales y
rechaza coincidencias dentro de números más largos, identificadores unidos
a letras y números ensamblados al quitar separadores. Solo compara título y
extracto, con comprobación obligatoria aunque se desactive el filtro literal
general. No usa como prueba el DNI reflejado en una URL ni rellena un título
ausente con esa URL.

Una mención encontrada incorpora su URL al contexto de la investigación para
que `dni_lookup` pueda examinar el documento en otra ronda. También se pueden
configurar URLs públicas de publicaciones concretas. No se consultan los
endpoints anteriores de lookup, incluso si sigue configurado
`APIS_NET_PE_TOKEN`; esa variable se conserva únicamente por compatibilidad.

El lector admite CSV delimitado por coma, punto y coma o tabulador; listas JSON
directas o bajo `records`/`data`; tablas HTML con encabezados; texto plano; y
PDF con texto. Los nombres solo se extraen si aparecen en el mismo registro
estructurado que el DNI completo, con columnas reconocidas de documento y
nombre. Las menciones en texto libre o PDF no asignan automáticamente los
nombres cercanos. No se conserva el dataset completo ni filas de otros DNIs.

Cada hallazgo conserva URL final, publicador, fecha de observación, formato,
fragmento y referencia al registro cuando existe. Se presenta como evidencia
publicada, con titularidad sin corroborar. Un nombre extraído se guarda como
candidato con su fuente y puede activar nuevas consultas del buscador si no
hay un nombre aportado. No sustituye `target.full_name` ni `context.full_name`;
si hay nombres contradictorios quedan como candidatos para revisar. Los motores
de reglas, híbrido y agente conservan estos pivotes y la cuota de consultas.

Los fallos, formatos no soportados y ausencia de coincidencias no generan
una entidad ficticia. Los estados técnicos quedan en `dni_public_results`,
incluidos errores HTTP, tamaño excesivo y errores de lectura. El inspector
muestra la fuente y el estado de asociación, y la raíz del grafo usa el DNI
cuando es el único identificador.

### Configuración y límites

```dotenv
# URLs reales de publicaciones abiertas, como una página o un CSV específico.
DNI_PUBLIC_SOURCE_URLS=[]
DNI_MAX_PUBLIC_SOURCES=4
```

Las URLs se expresan como una lista JSON de cadenas. Por ejemplo, pueden
incluir una publicación oficial de RENIEC o un recurso público identificado
en un portal de datos abiertos; no se incluye un padrón inventado por defecto.
Las URLs encontradas por el buscador comparten el mismo presupuesto con las
configuradas. Las peticiones no envían tokens de consulta; se rechazan URLs
con credenciales o parámetros habituales de autenticación, rutas de los
mirrors anteriores y destinos privados, incluso durante redirecciones.

Cada investigación examina como máximo cuatro pares DNI/fuente por defecto,
sin reintentos automáticos y con caché de intentos. Cada descarga se limita a
2 MB, hasta tres redirecciones y un timeout HTTP de diez segundos. Se revisan
como máximo 20.000 registros, veinte tablas HTML y tres coincidencias por
fuente. Las consultas siguen dentro del presupuesto global del buscador.

Para PDF se usa `pdftotext` de Poppler, con timeout de cinco segundos, primeras
treinta páginas y texto extraído limitado a 1 MB. El Dockerfile instala
`poppler-utils`; las instalaciones locales necesitan tener `pdftotext`
disponible. El respaldo para PDF escaneados se añadió posteriormente; véase
[la documentación del OCR](OCR_PDF.md).
Tampoco se rastrean automáticamente catálogos completos, ZIP, Excel o datasets
que excedan los límites: puede configurarse un recurso público concreto, y
la ausencia de coincidencia no demuestra que el DNI no aparezca en otras fuentes.

La suite añadida cubre fuentes simuladas de RENIEC, extracción del registro
exacto, candidatos sin reemplazo del nombre aportado, errores HTTP, límites,
redirecciones bloqueadas, PDF con texto, filtros obligatorios y el recorrido
completo búsqueda → documento público → búsqueda del nombre candidato.

Validación final: **390 pruebas aprobadas**, con tres pruebas de red/PostgreSQL
excluidas por la configuración de la suite. Las **44 pruebas específicas de DNI**
incluyen HTTP simulado y un PDF sintético leído realmente con Poppler.
TypeScript y ESLint del inspector finalizaron sin errores. También se
verificó la huella de configuración después de sustituir las URLs configuradas
por su hash, para no incluir posibles credenciales en la telemetría.
No se descargaron padrones reales ni se comprobó cobertura de publicaciones
electorales; el soporte de lectura no asegura que una fuente concreta exista
o contenga el DNI buscado. No se construyó la imagen Docker en esta revisión.
