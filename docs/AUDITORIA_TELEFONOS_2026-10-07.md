# Auditoría del motor de teléfonos

Fecha: 2026-10-07. Código revisado: `6f1fd09`. Dependencia instalada:
`phonenumbers 9.0.38`. No se modificó el comportamiento de la aplicación.

## Conclusión

El módulo es un analizador local del plan de numeración, no un buscador de
huella digital. Normaliza a E.164, consulta geocoder y operador por prefijo,
y construye enlaces de WhatsApp/Telegram. No realiza consultas externas ni
busca dónde se publicó el teléfono. Añadir búsqueda pública y pivotes tendría
más valor para el objetivo del proyecto que ampliar la lista de operadores.

## Método

- Lectura de `phone_lookup`, buscador, contexto, pivotes, presentación y pruebas.
- Ocho reproducciones locales con ejemplos del plan de numeración y datos de
  los tests existentes; sin consultar abonados, números de terceros ni cuentas.
- Revisión de documentación primaria de libphonenumber, PhoneInfoga, Twilio y OSIPTEL.
- `tests/test_tools.py`: 3 pruebas pasaron. Solo una prueba ejercita directamente
  el teléfono; verifica E.164 peruano y que exista el campo del enlace WhatsApp.

[Evidencia de las reproducciones](audits/phone-2026-10-07-code.json).

## Problemas comprobados

| Prioridad | Problema | Evidencia / efecto |
| --- | --- | --- |
| Alta | No hay búsqueda por teléfono. | `search_dorker.required_inputs` omite `phone`; un contexto que contiene solo teléfono tiene `can_run=False` y genera cero consultas. |
| Alta | Teléfonos descubiertos no producen pivotes. | `GravatarDeepTool` entrega `metadata.phones`, pero `TargetContext` no tiene teléfonos descubiertos y los pivotes no los procesan. Una reproducción dejó `context.phone=None`. |
| Alta | Operador sin distinguir origen y actualidad. | Se usa `carrier.name_for_number` de la base local; no hay consulta de portabilidad. El valor se presenta entre paréntesis sin indicar su procedencia. |
| Alta | Enlace generado presentado como evidencia. | Se guarda `wa.me/<número>` en `evidence_urls`, aunque nadie consultó WhatsApp ni comprobó registro. Los enlaces de mensajería son accesos derivados del número. |
| Media | Tipos de línea mal representados. | El ejemplo fijo peruano `+5111234567` aparece como “Operador móvil” cuando el carrier está vacío, aunque la biblioteca lo clasifica como fijo. |
| Media | País inventado en ausencia de geocoder. | El ejemplo no geográfico internacional `+80012345678` aparece como “Perú”. La biblioteca indica región `001`, tipo gratuito y geocoder vacío. |
| Media | Entradas inválidas inconsistentes. | `+51999` no produce resultado ni explicación; `abc` produce una entidad de teléfono con prioridad 0.5 y `valid=False`. Se captura cualquier excepción como si fuera un problema del formato. |
| Media | Información útil no mostrada. | La biblioteca ofrece país ISO, tipo de línea, motivo de longitud inválida y zonas horarias que no se guardan. El inspector tampoco tiene campos explícitos para el operador o la región del número. |

Los números con formato nacional peruano y el prefijo `51` sin `+` se
normalizaron correctamente en la muestra. No es necesario inventar una
corrección para esos dos casos; sí ampliar las pruebas a extensiones, países
extranjeros y entradas ambiguas, preservando la entrada original.

## Qué añadir y en qué orden

### 1. Corregir la semántica y completar el análisis local

Conservar `raw_input`, región predeterminada aplicada, E.164, formatos nacional
e internacional, país ISO, código de país, tipo de línea, posibles zonas
horarias, extensión y resultado de validación con motivo. Ausencia de datos
queda como desconocido; nunca se rellena con un país u operador inventado.

Separar `original_carrier` de `current_carrier`; este último queda desconocido
sin una fuente que lo consulte. `valid` expresa compatibilidad con el plan de
numeración, no que la línea esté asignada, activa o pertenezca al objetivo.
La [documentación de libphonenumber](https://github.com/google/libphonenumber/blob/master/FAQ.md)
explica ambas limitaciones. En Perú, la
[portabilidad permite conservar el número al cambiar de operador](https://www.osiptel.gob.pe/portal-del-usuario/preguntas-frecuentes/portabilidad-numerica).

Los enlaces de WhatsApp/Telegram deben llevar origen `derived` y estado de
registro desconocido, fuera de las evidencias observadas. La región y zona
horaria pertenecen al plan de numeración; no son la ubicación actual de la persona.

### 2. Buscar menciones públicas del número

Extender el buscador existente para consultas de E.164, formato nacional y
variantes habituales de espacios/separadores. Añadir búsquedas enfocadas en
páginas de contacto, documentos y perfiles públicos, respetando la cuota de
consultas y registrando cada URL, extracto y formato observado.

Un validador específico debe comparar números completos normalizados y contexto
de país. La búsqueda literal genérica actual puede aceptar subcadenas numéricas
sin límites, confundir DNI/identificadores con teléfonos o perder formatos con
separadores. Compartir solo los últimos dígitos no es suficiente.

[PhoneInfoga](https://github.com/sundowndev/phoneinfoga/blob/master/docs/getting-started/scanners.md)
usa dorks para buscar huellas públicas; su scanner `Googlesearch` genera enlaces
para abrir manualmente, sin garantizar resultados. El proyecto ya tiene Tavily
con respaldo DuckDuckGo, por lo que conviene integrar el método en ese motor y
conservar las fuentes, sin añadir una dependencia que repita el análisis local.

### 3. Extraer y conectar teléfonos observados

Añadir `discovered_phones` y `all_phones()` con normalización, deduplicación y
un presupuesto pequeño de números por investigación. Procesar `phones` y
`extracted_phones` de perfiles/fuentes; conservar dónde y en qué texto aparecen.
Usar extracción contextual de `phonenumbers` en biografías y páginas verificadas.

Relacionar fuente, perfil y teléfono como “teléfono publicado”. La asociación
no establece automáticamente titularidad: una página puede publicar el número
de una empresa, un representante, otra persona o una línea antigua. Las claves
de ejecución de los motores y del agente deben incluir la lista normalizada
para analizar los nuevos números sin repetir los anteriores.

### 4. Enriquecimiento externo opcional

Una integración autenticada con un proveedor de lookup puede aportar datos de
red y tipo de línea, diferenciándolos del catálogo local. Twilio documenta
[Line Type Intelligence como paquete de pago](https://www.twilio.com/docs/lookup/quickstart)
y [Line Status](https://www.twilio.com/docs/lookup/v2-api/line-status) como una
capacidad cuya cobertura debe comprobarse por país y red. No se validó aquí
su disponibilidad en Bitel, Claro, Entel o Movistar de Perú.

La integración necesitaría credenciales configuradas, límites de coste,
cache con fecha, estados `unsupported`/`unknown`/`error` y procedencia de cada
campo. No debería sustituir un dato desconocido con el operador original ni
prometer titular o ubicación precisa.

[Checa tus líneas](https://www.osiptel.gob.pe/portal-del-usuario/noticias/mas-de-77-000-lineas-moviles-no-reconocidas-fueron-dadas-de-baja-tras-reportes-en-checa-tus-lineas-del-osiptel/)
está orientado a consultar líneas por documento de identidad; no lo trataría
como una API abierta para resolver el titular desde cualquier teléfono.

## Pruebas necesarias al implementar

Números peruanos móviles y fijos; extranjeros y no geográficos; formatos
nacional/internacional; extensiones; entradas imposibles; ausencia de operador;
portabilidad; enlaces derivados sin evidencia de registro; números parciales
o confundidos con documentos; teléfonos observados que habilitan otra ronda;
deduplicación y límites; fallos y falta de cobertura de cualquier proveedor.

## Mejoras implementadas tras la auditoría

La revisión anterior describe el estado inicial. Ahora el motor valida y
normaliza números nacionales e internacionales, conserva la entrada original
y distingue móvil, fijo, VoIP y otras clases. Presenta formatos nacional,
internacional y E.164, país, región del plan de numeración, zonas horarias y
operador original cuando existen. No rellena datos desconocidos con Perú o
«Operador móvil». Los números inválidos generan un diagnóstico, sin crear
una entidad ficticia. Las extensiones se conservan como identidades distintas.

El operador actual, la actividad y la titularidad permanecen sin comprobar
con el análisis local. Los enlaces de contacto generados para tipos de línea
compatibles indican origen derivado y registro desconocido; no son evidencia
de una cuenta de WhatsApp o Telegram. Se omiten para números con extensión.

El buscador acepta investigaciones que solo contienen un teléfono y consulta
variantes completas del número en una consulta OR. Contrasta el título y
extracto del resultado con el número normalizado, incluso si se desactiva el
filtro literal general. No acepta coincidencias por los últimos dígitos ni
por la URL del resultado. Una mención en un extracto no confirma la página
completa ni identifica al titular del teléfono.

También extrae teléfonos de biografías verificadas y extractos de búsqueda.
Los números nacionales requieren una etiqueta de contacto; los internacionales
requieren el formato completo con `+`. La extracción limita cada texto a
20.000 caracteres, 100 intentos y cinco números. Los números descubiertos
habilitan otra ronda de análisis, conservando su fuente y deduplicando los
formatos equivalentes. Los enlaces «publica teléfono» y «menciona teléfono»
no permiten agrupar identidades automáticamente.

El presupuesto por investigación incluye el número inicial: por defecto,
tres números. Las consultas comparten la cuota general de búsqueda, por
defecto cinco consultas lógicas; cada una puede usar el respaldo DuckDuckGo
si falla Tavily. Los presupuestos y resultados se conservan entre llamadas
del agente y rondas de los motores. Los números con extensión se analizan
localmente, pero no se buscan ni consultan al proveedor de red.

### Configuración opcional del proveedor

Twilio Lookup está desactivado por defecto. Para habilitarlo, configurar las
variables del backend y seleccionar explícitamente los paquetes deseados:

```dotenv
PHONE_MAX_NUMBERS=3
PHONE_TWILIO_FIELDS=["line_type_intelligence"]
PHONE_TWILIO_API_KEY=<API key de Twilio>
PHONE_TWILIO_API_SECRET=<secreto de la API key>
```

`PHONE_TWILIO_FIELDS=[]` mantiene las consultas desactivadas. Puede seleccionarse
también `line_status`, solo o junto a `line_type_intelligence`. Los paquetes
pueden tener coste; el adaptador no sigue redirecciones ni reintenta peticiones
automáticamente. Mantiene resultados por investigación y muestra proveedor,
fecha, datos reportados y estados de error o falta de cobertura separados de
los datos del catálogo local. No admite paquetes de identidad de abonados.
Sin credenciales devuelve `not_configured` y no realiza peticiones.

No se consultaron números reales a Twilio ni se comprobó su cobertura para
operadores peruanos. La selección de un paquete no garantiza que el proveedor
disponga de datos para un número determinado.

### Validación realizada

- Backend: **352 pruebas aprobadas**, con tres pruebas de red/PostgreSQL
  excluidas por la configuración de la suite.
- Frontend: `tsc --noEmit` y ESLint de los dos archivos modificados, sin errores.
- Cobertura añadida: formatos, extensiones, entradas inválidas, números
  extranjeros y no geográficos, datos desconocidos, falsos positivos,
  extracción contextual, fuentes, pivotes, relaciones sin agrupación de
  identidad, presupuestos entre rondas y llamadas del agente, búsqueda solo
  por teléfono y respuestas correctas/erróneas del proveedor opcional.

Las peticiones HTTP de las pruebas fueron simuladas. Estas comprobaciones
validan el comportamiento del código, no la disponibilidad de Tavily,
DuckDuckGo o Twilio en producción ni la actividad de una línea real.
