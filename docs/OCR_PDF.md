# OCR de publicaciones PDF

El lector público de DNI usa primero `pdftotext`. Si encuentra el DNI completo
en esa capa de texto, conserva la página y no necesita OCR. Si no lo encuentra,
puede examinar páginas con una capa de texto escasa mediante OCR local de
Tesseract, sin enviar las imágenes a un servicio externo.

## Dependencias

El Dockerfile instala Poppler, Tesseract y los modelos de español e inglés.
En instalaciones locales se necesitan `pdftotext`, `pdftoppm`, `tesseract`
y un modelo compatible. En Debian/Ubuntu los paquetes son:

```sh
sudo apt-get install poppler-utils tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

`PDF_OCR_LANGUAGES=auto` prefiere los modelos instalados de español e inglés.
Si no existen y no se ha definido `TESSDATA_PREFIX`, puede usar modelos locales
en `backend/.ocr-models/`. Ese directorio está excluido de Git. En este entorno
se instaló allí el modelo oficial `eng.traineddata` de
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast).
No hay descargas automáticas de modelos al investigar un objetivo.
Un idioma configurado explícitamente debe estar disponible; no se cambia
silenciosamente a otro idioma. `TESSDATA_PREFIX` permite elegir otro directorio
de modelos mediante el entorno del proceso.

## Configuración

```dotenv
PDF_OCR_ENABLED=true
PDF_OCR_MAX_PAGES=3
PDF_OCR_TIMEOUT_SECONDS=20
PDF_OCR_LANGUAGES=auto
```

El respaldo examina páginas con menos de ochenta caracteres no blancos de texto
nativo dentro de las primeras tres páginas, por defecto. También funciona en
PDF mixtos con páginas de texto e imágenes. No garantiza detectar imágenes
dentro de una página que ya tiene una capa de texto extensa.

El presupuesto de OCR es de veinte segundos por documento para detección de
idiomas, renderizado y reconocimiento. Las opciones se limitan como máximo a
diez páginas y sesenta segundos, y se detiene al encontrar una coincidencia.
El renderizado limita el lado más largo de la imagen a 2.000 píxeles; cada PNG
se limita a 10 MB y cada salida TSV a 1 MB. Continúan aplicándose los límites
del lector público: descarga de 2 MB, cuatro fuentes por investigación,
lectura nativa de las primeras treinta páginas y cinco segundos para
`pdftotext`. El procesamiento se ejecuta en un trabajador para no bloquear el
bucle de peticiones del backend. Los temporales se eliminan al finalizar.

## Evidencia y limitaciones

Una coincidencia requiere el DNI completo como palabra reconocida, con
límites de identificador, y una puntuación de reconocimiento entre 85 y 100.
No se ensamblan fragmentos ni se sustituyen `O` por `0`, `I` por `1` u otras
letras por dígitos. Los ceros iniciales se conservan.

El hallazgo conserva la fuente pública, fecha, página, fragmento, idioma,
motor y puntuación de la palabra. También conserva el rectángulo de la palabra
en píxeles de la imagen renderizada: izquierda, arriba, ancho y alto. Se marca
`extraction_method=ocr`, `verification_status=ocr_candidate` y
`review_required=true`. La puntuación de OCR no es una probabilidad de identidad.
El inspector indica que deben revisarse los dígitos en el original.

El OCR no asigna automáticamente nombres cercanos al DNI y no habilita pivotes
de nombre. Los documentos borrosos, rotados o con maquetación compleja pueden
no producir coincidencias, incluso si una persona puede leerlos. La ausencia
de coincidencia dentro del presupuesto no demuestra ausencia del DNI en el PDF.
Falta de herramientas/idioma, desactivación, timeout, errores y límites de
salida se conservan como diagnósticos del formato en `dni_public_results`.

## Pruebas

La suite incluye comprobaciones de lectura exacta, ceros iniciales, confusión
de letras y dígitos, puntuaciones débiles o inválidas, herramientas/idiomas
ausentes, timeout y límite de páginas. Hay dos pruebas con Poppler y Tesseract
reales sobre un PDF sintético de imagen sin capa de texto: lectura directa e
integración con el lector de fuentes públicas, usando HTTP simulado. Ninguna
consulta un padrón real.

Validación de esta implementación: **403 pruebas aprobadas**, con tres pruebas
de red/PostgreSQL excluidas. Las 57 pruebas específicas de DNI y OCR pasaron,
incluidas las dos integraciones con OCR real. TypeScript y ESLint del inspector
finalizaron sin errores. No se construyó la imagen Docker: debe reconstruirse
para incorporar sus nuevas dependencias de OCR.
