# WhatsMyName en Person Map

Revisión local: 2026-10-15. `username_finder` conserva las recetas originales
de `backend/app/tools/data/wmn-data.json` además del motor nativo de Maigret.
Los datasets permanecen separados y se combinan en memoria.

| Snapshot incluido | Cantidad |
|---|---:|
| Entradas originales | 716 |
| Recetas utilizables tras exclusiones | 705 |
| Recetas con cuerpo POST | 23 |
| Recetas con cabeceras propias | 36 |
| Recetas que normalizan caracteres del alias | 23 |

SHA-256 del snapshot:
`779922223756f47d1512f81a5a2d0c69d19418fe5df1a2a9406c7cf18cf68f34`.
Se registra en la huella de cada investigación y en las claves de reutilización
de cobertura. El motor de búsqueda pasa a versión 5.

Antes, el catálogo deduplicaba por dominio y sustituía la receta de WhatsMyName
por la de Maigret. Solo quedaban 298 comprobaciones propias de WhatsMyName;
también se perdían variantes dentro del mismo dominio. Ahora, el catálogo de
escaneo conserva las 705 recetas, sus firmas `e_code`/`e_string`/`m_string`,
las rutas de usuario y organización, las consultas POST y sus cabeceras.
El catálogo compacto, usado para consultar plataformas, mantiene su deduplicación.

Maigret sigue ejecutando sus recetas y extrayendo metadatos. Mantener ambas
comprobaciones puede aumentar las peticiones a plataformas compartidas: son
rutas o firmas de detección alternativas. Los hallazgos conservan la fuente
del catálogo y siguen pasando por la deduplicación del motor de investigación.

La ejecución sigue el [esquema oficial de WhatsMyName](https://github.com/WebBreacher/WhatsMyName/blob/main/wmn-data-schema.json):
se respetan `post_body`, `headers`, `strip_bad_char` y `uri_pretty`. El alias
se codifica según se inserte en una URL, JSON o formulario. El alias original
se conserva como `requested_username` cuando se informa el alias consultado.
La consulta de control usa exactamente el mismo método y cabeceras. Una
respuesta de control que no cumple la firma de ausencia `m_code`/`m_string`
queda inconclusa; si cumple la firma de presencia, se rechaza el hallazgo.

Con la configuración pública habitual (sin Tor, I2P ni DNS), el catálogo de
escaneo tiene **5.868 recetas**. El límite de **3.400** incluye **705 de
WhatsMyName y 2.695 de Maigret**, antes de filtros y restricciones del alias.
`fast` usa un prefijo menor; `all` o `USERNAME_SCAN_MAX_SITES=0` permiten
recorrer el catálogo completo. Las exclusiones por categoría, entradas
desactivadas y el control obsoleto conocido de Fanslist siguen aplicándose.

Las pruebas locales cubren conservación del catálogo, POST JSON/formulario,
cabeceras, codificación del alias, normalización, redirecciones y controles
negativos, incluidas respuestas que dan positivo para cualquier alias. No se
ha vuelto a medir la disponibilidad en vivo de los 705 sitios. Tener una
receta integrada no asegura acceso a un sitio bloqueado, con CAPTCHA o caído.
Los informes nativos de Maigret exportan sus propias detecciones; los hallazgos
de WhatsMyName se incorporan al expediente habitual de Person Map.

Validación: 84 pruebas de catálogo/capacidades/integración pasaron; después,
102 pruebas de WhatsMyName, regresiones sociales y actualización de espacios
pasaron. Los grupos comparten algunas pruebas. Las pruebas que lanzan el
proceso Maigret se ejecutaron fuera del sandbox: dentro agotaban el tiempo de
espera. Una prueba marcada `network` quedó excluida.

Fuente: [WebBreacher/WhatsMyName](https://github.com/WebBreacher/WhatsMyName),
licencia CC BY-SA 4.0, © 2015–2026 Micah Hoffman y colaboradores.
