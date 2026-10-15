# Validación de las capacidades ampliadas de Maigret

Se repitió el objetivo `xBiltTom` desde la investigación exitosa
`f3e7cc69-ff1f-486b-a7ca-634065e5a6ec`, creando la investigación tradicional
**`a94e1894-fd31-4051-aff4-b4562edfcbce`**. Se usaron base, orquestador y fuentes
reales, con estrategia `rule_based`, ejecución `internal` e IA desactivada.
La investigación de origen y el entorno del servidor se conservaron.

## Resultado

| Medida | Referencia anterior | Ampliación final |
|---|---:|---:|
| Entidades | 17 | 19 |
| Perfiles sociales | 7 | 10 |
| Perfiles con detección nativa | No aplicaba | 8 |
| Tiempo total | 135,93 s | 181,94 s |
| Herramientas fallidas en la ampliación | — | 0 |

La configuración sigue limitando el barrido habitual a 500 plataformas y tres
alias: se hicieron 1.499 comprobaciones, un descarte por formato y seis rechazos
por control negativo. El catálogo disponible ahora incluye 5.461 recetas con
variantes, pero este ensayo no consultó todo ese catálogo.

Se recuperaron GitHub, X, Disqus, Picsart, Snapchat y el candidato de LinkedIn.
Se agregaron LeetCode y GitHub Gist, además de **ORCID y el registro de autor
OpenAlex**. Los dos últimos se buscaron mediante el ID
`0009-0002-0165-5976`, descubierto por la herramienta académica. Se ejecutaron
sus cinco recetas correspondientes: ORCID y OpenAlex dieron positivos que
pasaron controles; arXiv y Scholia no detectaron registro; DBLP quedó inconcluso
por protección de bots. Los extractores nativos identificados incluyen ORCID
API y OpenAlex Authors API.

`maigret_enricher` terminó en 32,192 s y aportó esos dos registros, además de
guardar candidatos derivados de las diez URLs adicionales intentadas. Esas
URLs sin datos no generan cuentas ni menciones. No reapareció la URL histórica
de búsqueda de Roblox, que no era una cuenta individual.

La detección y sus controles prueban la existencia del recurso, no su pertenencia
al objetivo. La búsqueda académica y su ORCID conservan su condición de
candidatos de asociación. El estado `Unknown` no significa ausencia.

El tiempo final fue mayor que el histórico. Las diferencias de catálogo,
enriquecimiento, respuestas de los buscadores, condiciones de red y ejecución
simultánea de la suite impiden considerarlo una comparación controlada de
rendimiento o una medición general de precisión.

## Corrección descubierta por el ensayo

El [primer ensayo de esta ampliación](2026-10-13-maigret-expanded-initial.json)
terminó sin errores y con ocho perfiles nativos, pero añadió menciones de URLs
generadas sin contenido. Se corrigió para guardar esos identificadores en el
runtime, sin fabricar entidades de página. El
[ensayo final](2026-10-13-maigret-expanded-live.json) verifica esa corrección.

Se separó también el presupuesto de nuevas URLs intentadas de la caché de
páginas que ya había leído el motor nativo. Se conserva el mismo límite de
consultas adicionales sin consumirlo por trabajo previamente realizado.

## Alcance de las pruebas

- Suite local final: **568 pruebas aprobadas; nueve excluidas** por marcadores.
- Integración PostgreSQL/MCP: **seis pruebas aprobadas**, en esquema temporal.
- TypeScript y ESLint de los archivos modificados: aprobados.
- Firefox de pruebas: controles revisados a 1440 y 390 px, sin desbordamiento;
  se comprobó el envío solo con ORCID y el modo completo interceptando el POST.
  No se creó otra investigación desde esa prueba de interfaz.
- Los diez formatos nativos se generaron con el worker real y respuestas
  controladas, sin solicitudes de red durante la exportación. El PDF se descargó
  también por HTTP desde la instancia temporal del backend.
  La descarga produjo un PDF de cuatro páginas con la declaración de alcance.
- Cookies, proxies, Tor/I2P y solver tienen pruebas de contrato/controladas.
  No se configuraron servicios Tor/I2P o FlareSolverr reales para este ensayo.
- El modo completo se verificó mediante catálogo y ampliación de cobertura;
  la prueba de red conservó el límite habitual de 500.

La documentación de uso, configuración, informes y auditoría está en
[MAIGRET.md](../MAIGRET.md). Las métricas omiten contactos, DNI y contenido de
exposiciones; conservan URLs públicas, estados y datos de reproducibilidad.
