# Ensayo piloto: agente por MCP frente al motor de reglas

Fecha: 9 de octubre de 2026. Se repitió un expediente propio de Bilton Junior Novoa Arce, con autorización del usuario. Se conservaron los expedientes históricos y se crearon dos nuevos. El histórico elegido tenía 29 observaciones y 154,96 segundos; se usaron sus entradas, sin suministrar sus hallazgos al agente. El caso histórico de Alexis tenía 42 observaciones, pero no fue el participante de este ensayo.

## Resultado observado

| Medida | Agente por MCP | Reglas tradicionales |
| --- | ---: | ---: |
| Tiempo registrado de la corrida | 10 min 35 s | 3 min 24 s |
| Observaciones persistidas | 20 | 23 |
| Referencias reconocidas por el usuario recuperadas | 4/4 | 4/4 |
| Ejecuciones de herramientas | 22 | 42 |
| Tiempo con alguna herramienta activa, unión de intervalos de la traza | 3 min 00 s | 3 min 24 s |
| Cobertura del catálogo | 500 sitios × 3 alias | 500 sitios × 3 alias |

Las reglas fueron más rápidas en esta pareja de corridas. El agente recuperó las mismas cuatro referencias conocidas y guardó una revisión explícita de las coincidencias, pero no demostró una mejora general de precisión o cobertura. Los tiempos de las herramientas no se suman para compararlos con el tiempo total: aquí se muestra la unión de intervalos, que cuenta una sola vez los trabajos solapados.

La sesión MCP medida duró exactamente 635.220 segundos. Incluye deliberación, comunicación de progreso, manejo del ensayo, esperas y validación del usuario durante la sesión. Una parte importante transcurrió sin herramientas activas; esos intervalos no pueden atribuirse automáticamente a coste de red o a una deficiencia del transporte MCP. Es una prueba interactiva, no un benchmark autónomo. Una sesión posterior dedicada a guardar la comparación queda fuera de esta medición; la web puede mostrar la suma de todas las sesiones.

## Condiciones comprobadas

Las entradas iniciales y todos los campos `config_*` guardados por el backend coinciden entre los dos expedientes. Ambas corridas usaron Tavily, un máximo de cinco consultas en `search_dorker`, catálogo de 500 sitios, 40 conexiones HTTP globales, cuatro por host y concurrencia efectiva de barrido de 24. Los alias efectivamente barridos fueron `xBiltTom`, `bjnovoaar` y `biltonjr`, cada uno sobre 500 entradas del catálogo. La cobertura representa entradas recorridas, no 500 respuestas exitosas por alias.

El agente tuvo como máximo tres herramientas simultáneas; las reglas despacharon herramientas en paralelo por ronda. El agente no utilizó navegación propia ni `public_page_reader`. La selección y las consultas fueron diferentes: el agente priorizó nombre y alias; las reglas también buscaron el identificador numérico inicial. El agente omitió `domain_finder` al no encontrar evidencia de un dominio personal. El catálogo y los presupuestos máximos fueron iguales; las decisiones y el trabajo real no fueron idénticos.

Se ejecutó primero MCP y después reglas, sin solaparlas. El orden, las cachés del proceso, cuotas y variaciones de las fuentes son posibles factores de confusión. Hay una sola pareja de corridas. Se registró `model=null`: la plataforma no verificó el modelo del cliente. El motor realmente usado en la segunda corrida fue `rules`, aunque la configuración del servidor tenga IA habilitada.

## Referencias y revisión de calidad

El usuario reconoció como propias estas cuatro referencias, recuperadas por ambos caminos:

- [GitHub xBiltTom](https://github.com/xBiltTom). El expediente incluye evidencia del perfil, API y commit. Varias herramientas consultaron recursos relacionados; no equivalen a confirmaciones independientes.
- [LinkedIn](https://pe.linkedin.com/in/bilton-junior-novoa-arce-6a52a3281). Se encontró el perfil específico; la declaración del usuario respaldó su pertenencia. Los directorios genéricos de LinkedIn no son perfiles del objetivo.
- [ORCID](https://orcid.org/0009-0002-0165-5976). Se recuperó como metadato del [autor en OpenAlex](https://openalex.org/A5156769335), no como una lectura directa de ORCID.
- [Disqus biltonjr](https://disqus.com/by/biltonjr/). Su pertenencia se confirmó por el usuario después de cerrar la corrida MCP.

Son referencias reconocidas a posteriori, seleccionadas entre los resultados. El 4/4 no es una medida de recall de toda la huella digital ni permite calcular precisión general. El usuario indicó que X podría ser suyo; no recordó Picsart ni Roblox. Esas coincidencias siguen pendientes. Facebook y Snapchat tampoco tienen validación de pertenencia en este ensayo.

En MCP se señalaron seis observaciones sin respaldo para atribuirlas al objetivo: un directorio genérico de LinkedIn y cinco resultados de artículos o autores distintos encontrados por las anclas separadas «Bilton» y «Novoa». Las consultas posteriores añadieron dos documentos vinculados a UNT; sus menciones se conservaron sin asumir atribución personal verificada.

En reglas se revisaron once observaciones sin respaldo de atribución: cuatro menciones de anuncios/productos donde el identificador numérico coincide con un código comercial, tres directorios genéricos de LinkedIn, una observación documental del mismo anuncio y tres dominios comerciales derivados de esos candidatos. La coincidencia numérica, aunque literal, no acredita que una página trate del DNI del objetivo. Estos son recuentos de observaciones revisadas; no una tasa completa de falsos positivos. No se eliminaron ni alteraron hallazgos para mejorar las cifras.

## Implicaciones para mejorar el sistema

Este ensayo muestra dos puntos concretos: las coincidencias literales necesitan contexto semántico antes de presentarse como evidencia relevante; y las URLs encontradas en una búsqueda no deberían convertirse automáticamente en candidatos a infraestructura personal. Las consultas de Certificate Transparency se repitieron en varias rondas y tuvieron respuestas degradadas. La revisión del agente identificó el problema, pero sus llamadas y deliberación añadieron tiempo.

Para una siguiente evaluación, hay que optimizar esos puntos también en las reglas, fijar un protocolo autónomo sin interacción humana durante la medición y repetir varios casos alternando el orden. Deben revisarse los resultados con referencias previamente establecidas y un evaluador independiente. Esta pareja aporta evidencia exploratoria, sin demostrar que un agente sea superior en general.

## Expedientes y trazabilidad

- [Expediente MCP](http://localhost:3000/investigation/f74bf3a2-a084-48c4-a734-2e1b9fa1ee2d): plan, justificaciones, fuentes y notas de análisis.
- [Nueva corrida tradicional](http://localhost:3000/investigation/8c23b723-598a-4ae3-a2f7-4ad549092277): observaciones y traza de reglas.
- Fuente histórica de las entradas: `3e770c8f-2098-4e6b-8a99-a6c13e4d172c`.
- Sesión MCP primaria medida: `600ec991-43b2-4941-846c-5ba8e459c322`.
- Código: `1333b0d22428ca9989674ae7d16674d9a05fb38d`. El cambio local existente en `docs/MCP.md` era documental.
- Resumen estructurado sin correos, teléfono, DNI ni resultados de exposición: [2026-10-09-mcp-vs-rules.json](2026-10-09-mcp-vs-rules.json).

Los datos completos permanecen en los expedientes locales y sus trazas. Este informe no publica sus identificadores privados.
