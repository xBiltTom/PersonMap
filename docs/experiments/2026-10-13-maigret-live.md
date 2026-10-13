# Validación real de Maigret en modo tradicional

La investigación tradicional terminó sin errores de herramientas y ejecutó el
motor Maigret 0.6.6 contra fuentes reales. Recuperó cinco perfiles presentes en
el registro anterior y agregó LeetCode y GitHub Gist. Obtuvo datos mediante los
extractores nativos de GitHub, LeetCode, Disqus, Picsart y Snapchat. Este caso
confirma que la integración funciona; no constituye una medición general de
precisión ni demuestra superioridad sobre todas las herramientas.

## Condiciones

- Objetivo: `xBiltTom`, elegido entre investigaciones completadas de la base.
- Referencia: `f3e7cc69-ff1f-486b-a7ca-634065e5a6ec`, del 11 de octubre.
- Validación final: `1e90de8e-33c9-412a-9306-85332a423462`.
- Orquestador, base de datos, herramientas registradas y transporte reales,
  sin respuestas simuladas. Estrategia `rule_based`, ejecución `internal` e IA
  desactivada en el proceso de validación. La referencia usaba el motor de
  reglas y registra `ai_enhanced=true` en el posprocesamiento.
- Se creó un objetivo e investigación separados, copiando los campos y el
  consentimiento almacenado. La referencia y el archivo de entorno se
  conservaron.
- Límite vigente: 500 plataformas por alias y tres alias. El catálogo nuevo
  selecciona 291 recetas nativas y 209 complementarias; la referencia empleaba
  500 recetas de WhatsMyName. No son exactamente las mismas plataformas.
- Presupuesto actual de HTTP: 40 solicitudes concurrentes globales; cuota de
  `username_finder`: 24, compartida por las dos ramas del barrido.
- Maigret: `0.6.6`; SHA-256 del catálogo incluido:
  `ef6ca66efa174209c10205ff86f7e975b591128681710639fdc786ff05e662da`.

## Resultados finales

| Medida | Registro anterior | Validación final |
|---|---:|---:|
| Tiempo total | 135,93 s | 218,92 s |
| Entidades de todos los tipos | 17 | 13 |
| Perfiles sociales | 7 | 7 |
| Perfiles con detección nativa de Maigret | No aplicaba | 6 |
| Ejecuciones de herramientas fallidas | — | 0 de 35 |

Se completó la cobertura de 500 plataformas para `xBiltTom`, `bjnovoaar` y
`biltonjr`: **1.499 comprobaciones**, un descarte previo por formato y **seis
rechazos por control negativo**. Las comprobaciones no equivalen al número de
peticiones HTTP: los controles, reintentos y extractores hacen consultas
adicionales. Las tres ejecuciones de `username_finder` tardaron 70,783 s,
71,639 s y 68,854 s y produjeron tres, cero y cuatro hallazgos respectivamente.

| Perfil | Comparación | Estado final | Extractor nativo |
|---|---|---|---|
| GitHub `xBiltTom` | Recuperado | Verificado; bio y avatar | GitHub API |
| X `biltonjr` | Recuperado | Verificado; bio | Complementario |
| Disqus `biltonjr` | Recuperado | Verificado; avatar; URL `/by/` | Disqus API |
| Picsart `biltonjr` | Recuperado | Candidato; avatar | Picsart API |
| Snapchat `biltonjr` | Recuperado | Verificado; bio, avatar y enlaces | Snapchat |
| LeetCode `xBiltTom` | Nuevo | Candidato; avatar | LeetCode GraphQL |
| GitHub Gist `xBiltTom` | Nuevo | Verificado; bio y avatar | Sin extractor identificado |

Los siete perfiles pasaron el control negativo. «Verificado» describe la
existencia del recurso, no su pertenencia a la persona. GitHub conserva las
fuentes de `github_deep_scanner`, `email_checker`, `social_url_extractor` y
`social_verifier` junto con Maigret; las evidencias de especialistas se fusionan.

No reaparecieron el candidato de LinkedIn ni la URL de búsqueda de usuarios
de Roblox de la referencia. LinkedIn venía de `social_url_extractor`; en esta
ejecución hubo una mención de búsqueda frente a seis en la referencia. Roblox
era una página de búsqueda, no una URL de cuenta individual. La diferencia en
el total de entidades también incluye dos resultados académicos frente a uno.

Upstream produjo 73, 76 y 71 resultados `Unknown` para los tres alias;
permanecen inconclusos y no se interpretan como cuentas inexistentes. El tiempo
final fue mayor que el histórico. El catálogo, las consultas adicionales, el
presupuesto compartido y las condiciones externas impiden tratar esta
comparación como un ensayo controlado de rendimiento. Durante la ejecución
final también corría la suite local de regresión.

## Fallos encontrados y correcciones validadas

1. El primer ensayo falló en los tres barridos nativos: el cliente ya había
   descomprimido el cuerpo, pero el puente conservaba `Content-Encoding` y
   provocaba una segunda descompresión. Se eliminaron esas cabeceras al
   reconstruir respuestas. Las pruebas cubren HTTP comprimido, RPC y curl.
2. El segundo ensayo terminó sin fallos y con seis perfiles nativos. Expuso
   una URL pública incorrecta en la receta original de Disqus. Se corrigió a
   `/by/{username}/` en catálogo y worker, conservando el endpoint API. La
   prueba final recupera el mismo perfil histórico y lo verifica.
3. Las ramas Maigret y complementaria tenían semáforos independientes. Ahora
   comparten una cuota de herramienta. Una prueba con el worker real y ambas
   ramas comprueba que el máximo simultáneo respeta el presupuesto.

Validación local: **72 pruebas dirigidas aprobadas**; suite predeterminada:
**534 aprobadas y nueve excluidas** por sus marcadores de red/base de datos.
La investigación documentada arriba prueba el recorrido real con red y base.

## Evidencia y repetición

- [Ensayo inicial con fallo](2026-10-12-maigret-live-initial.json).
- [Ensayo tras corregir compresión](2026-10-12-maigret-live-compression-fixed.json).
- [Resultado final y comparación de perfiles](2026-10-13-maigret-live.json).
- [Arquitectura y configuración](../MAIGRET.md).

Desde `backend`:

```bash
.venv/bin/python scripts/validate_maigret_live.py run --source f3e7cc69-ff1f-486b-a7ca-634065e5a6ec --output ../docs/experiments/maigret-live.json
```

El script crea otra investigación. Los informes incluyen URLs públicas y
estadísticas; omiten correos, teléfonos, DNI y contenido de exposiciones.
