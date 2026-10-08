# Auditoría del buscador y evaluación de TinyFish — 2026-10-07

## Resultado

Tavily respondió correctamente con la clave configurada en una comprobación
real. El motor tiene una base útil — consultas entrecomilladas, comparación
local, cuotas y filtros específicos de teléfono/DNI — pero conserva problemas
reproducibles de cobertura y falsos positivos. Conviene corregirlos y ampliar
la lectura de fuentes antes de considerar óptimo el sistema.

TinyFish es un complemento viable para búsqueda y extracción; no se probó su
API ni se incorporó durante esta auditoría. No se modificó código de aplicación.

## Verificación real de Tavily

Se consultó documentación pública del proveedor, sin datos de personas, con
`"Tavily" "documentation"`, profundidad `basic` y tres resultados máximos:

| Variante | HTTP | Resultados | Coincidencias según el comparador local actual | Tiempo | Créditos |
| --- | --- | --- | --- | --- | --- |
| Sin solicitar `exact_match` | 200 | 3 | 3 | 1,81 s | 1 |
| Con `exact_match=true` | 200 | 3 | 2 | 1,31 s | 1 |

La API aceptó la clave y ambas variantes. El comentario que afirma que
`exact_match` siempre devuelve cero resultados ya no describe esta prueba.
Tampoco se debe concluir que la opción garantice todos los términos en cada
extracto, ni que dos llamadas midan cobertura OSINT, disponibilidad sostenida
o rendimiento sobre personas. Es una comprobación de conectividad y contrato
del proveedor, no un benchmark del motor completo.

La prueba autenticada se hizo fuera del sandbox, cuya resolución DNS está
restringida, mediante un cliente HTTP dirigido al endpoint oficial. El
[registro de resultados](audits/search-2026-10-07-live.json) conserva únicamente
estados, métricas, dominios y uso; no contiene credenciales.

## Problemas reproducidos en el código

1. **Respaldo por lote en lugar de por consulta.** Si la primera consulta tiene
   resultados y las otras cuatro quedan vacías, el lote devuelve lo encontrado
   y DuckDuckGo no intenta ninguna de las cuatro pendientes. Un fallo de una
   consulta también puede quedar oculto por el éxito de otra.
2. **Cuota sin reparto entre identificadores.** Con correo, teléfono, DNI,
   nombre y alias, las cinco primeras consultas del ejemplo de prueba excluyen
   el alias. Nuevos pivotes pueden llegar cuando ya no hay cuota disponible.
3. **Identificadores descubiertos sin consultas correspondientes.** Se usan
   `context.email` y `context.username`, sin recorrer `all_emails()` y
   `all_usernames()`. Del listado de nombres candidatos solo se usa el primero
   si falta el nombre inicial. Las claves de ejecución cambian al descubrir
   datos, pero eso no asegura una consulta sobre ellos.
4. **Comparador genérico permisivo.** Acepta `ana` dentro de `banana`,
   `person@example.test` dentro de `otherperson@example.test`, un alias presente
   solo en `?q=` de la URL y `José` frente a `Josh` después de eliminar `é`
   del texto normalizado. DNI y teléfonos ya tienen comparadores específicos;
   faltan reglas equivalentes para alias, correo y nombres.
5. **Filtros de dominio sin comprobación propia.** El respaldo aceptó una URL
   de otro dominio en una consulta limitada a `github.com`. En Tavily se confía
   en el filtro de API; la validación común debería contrastar el hostname y
   sus subdominios, independientemente del proveedor.
6. **Validación incompleta de respuestas y URLs.** Una respuesta Tavily 200 con
   JSON de lista causa `AttributeError`. Un score no numérico puede interrumpir
   el parseo. `_build_finding` acepta `http-not-a-valid-url` porque solo comprueba
   que comience por `http`. Un resultado malformado no debe perder todo el lote.
7. **Errores confundidos con ausencia de resultados.** Una clave inválida,
   cuota agotada, timeout o JSON ilegible pueden terminar en `[]`, sin un
   diagnóstico específico de búsqueda. Las consultas se marcan ejecutadas
   antes de intentarlas y la cuota cuenta consultas lógicas, no reintentos HTTP
   ni consumo real del proveedor.
8. **Lectura de fuentes incompleta.** El buscador guarda URL, título y extracto.
   La verificación posterior cubre perfiles reconocidos y documentos por DNI,
   pero no existe una lectura general compartida de artículos, portales y
   páginas dinámicas. Un extracto sigue siendo una pista, no verificación del
   contenido íntegro de la página.

El [registro de reproducción local](audits/search-2026-10-07-code.json) usa
entradas sintéticas y HTTP simulado. Las 106 pruebas existentes de buscador,
teléfono y DNI pasaron; no cubren todos los errores anteriores.

## Mejoras recomendadas

- Despachar respaldo por consulta pendiente, con límite global de llamadas,
  deadlines y estados por proveedor: éxito, vacío, filtrado, autenticación,
  cuota, timeout y respuesta inválida. Evitar reintentos costosos indiscriminados.
- Distribuir la cuota entre identificadores y reservar capacidad para pivotes.
  Consultar datos descubiertos normalizados, deduplicando consultas y variantes.
  La solución no es simplemente aumentar el límite para todos los objetivos.
- Comparar correos completos, alias con límites/contexto y nombres mediante
  normalización Unicode que preserve letras y permita acentos equivalentes.
  Separar coincidencia de identificador, contexto institucional e identidad.
  La URL puede contribuir cuando es una ruta de perfil reconocida, pero reflejar
  el término en una query no constituye evidencia.
- Validar esquemas, scores y URLs por resultado; comprobar dominios también en
  el cliente. Conservar todas las consultas y procedencias que apoyan una fuente.
- Leer un número acotado de fuentes candidatas y guardar fragmento observado,
  URL final y fecha. Mantener los lectores CSV/JSON/PDF/OCR actuales para las
  publicaciones correspondientes.
- Revisar `exact_match` como opción evaluable, manteniendo validación propia.
  Tavily también ofrece [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)
  para contenido de URLs; `advanced` contempla tablas y contenido embebido,
  con costes y latencias propios. Search y Extract deben tener presupuestos
  separados. [Referencia de Search](https://docs.tavily.com/documentation/api-reference/endpoint/search).

## Incorporación propuesta de TinyFish

La [documentación oficial](https://docs.tinyfish.ai/) distingue Search, Fetch,
Agent, Browser y Research. Las dos primeras piezas cubren necesidades concretas
del proyecto:

| Función | Propuesta para Person Map |
| --- | --- |
| Descubrir fuentes | Tavily como principal; TinySearch como respaldo por consulta o comparación acotada; DuckDuckGo como último respaldo. |
| Leer fuentes | Lectura local para documentos; Tavily Extract o TinyFetch para extraer páginas candidatas y contrastar el contenido observado. |
| Navegar páginas públicas | TinyAgent opcional para menús, filtros y paginación que necesiten navegación; activación selectiva con presupuesto de pasos/tiempo. |
| Validar evidencia | Comparadores y reglas propias, conservando procedencia y nivel de asociación. Las respuestas de un agente no confirman identidad por sí solas. |

[TinySearch](https://docs.tinyfish.ai/search-api/reference) ofrece resultados
estructurados, filtros de dominio y contexto de país/idioma con autenticación
`X-API-Key`. [TinyFetch](https://docs.tinyfish.ai/fetch-api/reference) permite
extraer contenido y metadatos de las URLs, incluyendo su URL final. El
[proveedor describe renderizado de páginas](https://www.tinyfish.ai/) entre
sus capacidades; conviene comprobarlo en los sitios concretos del proyecto.

Search y Fetch se anuncian gratuitos dentro de sus límites; Agent y Browser
tienen facturación propia. Las referencias de API contemplan agotamiento de
la asignación y HTTP 402, por lo que deben verificarse los límites de la cuenta
antes de definir la política automática. No se asume navegación ilimitada o
ausencia de coste. [Precios](https://www.tinyfish.ai/pricing).

El primer paso recomendado es corregir el coordinador y los comparadores,
después añadir TinySearch/TinyFetch mediante adaptadores opcionales con clave
y presupuesto. TinyAgent aportaría una tercera etapa para navegación pública
cuando haga falta. El flujo seguirá usando fuentes públicas; la autenticación
del proveedor no autoriza iniciar sesiones en las páginas de los objetivos.

Antes de cambiar el proveedor principal, conviene comparar precisión, fuentes
útiles adicionales, latencia y consumo sobre un conjunto reproducible de
consultas públicas. No se atribuye a TinyFish una superioridad de cobertura
que todavía no se ha medido en este proyecto.

## Implementación posterior a la auditoría

Se corrigieron el respaldo por consulta, las coincidencias parciales, los filtros
de dominio y la tolerancia a respuestas malformadas. Se incorporaron TinyFish Search
opcional y un lector público acotado con TinyFetch opcional. Sin clave no se llama
a TinyFish. Los diagnósticos iniciales de este informe y su JSON describen el estado
**anterior** a estos cambios. Configuración, funcionamiento y límites actuales:
[MOTOR_BUSQUEDA.md](MOTOR_BUSQUEDA.md).

Validación de la implementación: 456 pruebas aprobadas, 3 excluidas (red/DB).
Dos consultas reales adicionales a Tavily: siete coincidencias aceptadas en la
consulta general y ninguna en la restringida a documentación; un crédito cada
una. TinyFish permanece validado mediante HTTP simulado, sin prueba real con clave.
