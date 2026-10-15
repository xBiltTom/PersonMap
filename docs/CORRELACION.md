# Correlación de observaciones y cercanía visual

La política 2 relaciona evidencias y ordena candidatos. **No declara que una
cuenta pertenezca a una persona ni calcula probabilidades de identidad.**
`ownership_status` permanece `unverified`. Los grupos son conjuntos de
observaciones conectadas, no personas identificadas.

## Evidencia directa respecto al objetivo

La comparación utiliza los datos iniciales del objetivo. No incorpora como
verdad nuevos correos o nombres descubiertos al buscar otros candidatos.

| Señal | Tratamiento visual |
| --- | --- |
| Correo publicado en el perfil o contacto de una bio verificada | Prioridad alta, base 0,82 |
| Teléfono publicado en un perfil, normalizado al mismo número | Prioridad alta, base 0,78 |
| Asociación exacta de correo devuelta por GHunt/Gravatar | Base 0,72; se distingue de una declaración pública de correo |
| ORCID/GAIA observado igual al identificador inicial | Base 0,72; el identificador debe corresponder al perfil |
| Alias observado y correo compartido | Refuerzo pequeño, +0,06; el alias solo no atrae al objetivo |
| Nombre completo observado | Contexto débil, 0,12; con afiliación coincidente, 0,20 |
| Correo en commit, mención documental o perfil todavía candidato | Contexto débil, hasta 0,16 |
| Coincidencia de alias sin correo ni otro dato | Cero atracción directa al objetivo |
| URL que contiene el correo/nombre, avatar presente o puntuación previa de una herramienta | No generan por sí solos evidencia directa |

Se toma la señal de contacto principal más fuerte, con refuerzos acotados por
nombre observado y contactos complementarios; el máximo visual es 0,94. Estos
valores controlan distancias y orden de revisión: **0,82 no significa un 82 %
de probabilidad**. Repetir el mismo dato o añadir herramientas que lo copien
no aumenta el peso. No se usa `ToolFinding.confidence` ni el score de un
buscador/verificador como certeza de identidad.

Los correos se comparan completos, sin eliminar puntos ni etiquetas `+`.
Los teléfonos usan la normalización del motor telefónico, incluidas extensiones.
Los nombres se comparan completos, tolerando tildes y separadores; no se
expanden iniciales ni se leen nombres de una URL, título genérico, consulta o
campo inferido. Esto conserva homónimos como candidatos y puede omitir variantes.

Las señales conservan `kind`, `value`, `role`, `field`, herramienta y URL de
origen cuando existe. GHunt Play Games, colaboradores de Drive, coautores y
parámetros de búsqueda no se convierten automáticamente en contactos del objetivo.
Los identificadores declarados por un agente al importar una página son contexto
reportado; el servidor no los presenta como contactos de perfil verificados.

## Relaciones y vecindarios entre candidatos

Dos perfiles pueden compartir correo o teléfono aunque ese dato no sea el del
objetivo. Esa relación se conserva entre ellos y no cambia su afinidad directa
con el nodo central. Lo mismo ocurre con enlaces de perfil, ORCID/GAIA y autorías
documentadas mediante identificadores de autor/publicación.

El mismo nombre, o nombre y afiliación, puede crear una relación contextual y
un vecindario visual. Estas relaciones **no unen componentes por sí solas**.
Compartir nombre, avatar o alias no identifica a una persona. Un alias entre
candidatos independientes puede mostrarse como contexto muy débil; se evitan
las conexiones tautológicas del mismo barrido de alias.

Ejemplo: A publica el correo inicial y B comparte nombre con A. A se coloca
cerca del objetivo; B puede colocarse junto a A, hacia el exterior. B conserva
peso directo cero si no comparte un dato inicial. No recibe el correo ni la
afinidad de A. La pertenencia a un componente tampoco transmite evidencia.

Los enlaces se comparan por recurso canónico exacto, sin aceptar prefijos o
dominios parecidos. Se preserva la distinción de mayúsculas en los IDs de canal
de YouTube y los demás identificadores sensibles a ella. Las autorías se
vinculan por ID de OpenAlex u ORCID observado, no por todos los nombres del artículo.

Se genera un conjunto disperso de relaciones mediante índices de señales,
vecinos y un árbol de evidencia fuerte. Así se mantiene la conectividad de un
grupo grande aunque su nodo central supere seis conexiones; las aristas
adicionales se acotan. No se construye una camarilla cuadrática de perfiles que
comparten el mismo correo. Las menciones y los nombres no se convierten en
puentes fuertes para atribuir identidades.

Brechas, infostealers y señales de registro por correo se conservan aparte:
son registros ligados a una consulta, no cuentas identificadas de la persona.
Una señal de registro puede tener cercanía contextual, sin unir cuentas por ello.

## Motor, REST, mapa y MCP

La extracción de roles y las relaciones viven en `app/identity/evidence.py`.
La persistencia usa esas reglas en los motores tradicional, híbrido y agente.
La deduplicación conserva `correlation_observations` por origen: verificar el
perfil con una segunda herramienta no convierte en publicado un correo que la
primera herramienta solo había propuesto como candidato.

El mapa, los grupos REST y el contexto MCP usan la misma proyección vigente.
Se recalcula al leer los metadatos existentes, sin modificar los expedientes
históricos ni ejecutar de nuevo sus fuentes. Los metadatos antiguos que no
conservaron un dato o su procedencia no se pueden reconstruir desde el grafo.
Una posterior ejecución sí guarda las nuevas relaciones y observaciones.

El contexto MCP expone `correlation` con la versión, semántica, candidatos
priorizados y conteo de relaciones. `list_findings`/`get_finding` incluyen la
afinidad directa del hallazgo; el contexto añade el ancla de vecindario cuando
corresponde. Las evaluaciones redactadas por el agente siguen siendo hipótesis
con fuentes, no hechos aceptados automáticamente ni instrucciones para el motor.

El inspector explica las señales y las colocaciones por vecindario, sin mostrar
porcentajes de pertenencia. Ocultar líneas de procedencia no oculta las
coincidencias factuales con el objetivo. GraphML conserva la evidencia y la
semántica visual de la proyección exportada.

## Comprobaciones

```bash
cd backend
.venv/bin/pytest tests/test_correlation_evidence.py tests/test_persistence.py tests/test_resolver.py -q
.venv/bin/pytest tests/test_mcp_workspace_db.py -m db -q
cd ../frontend
pnpm test:graph
pnpm exec tsc --noEmit
```

Los casos usan datos ficticios: correo y teléfono compartidos, alias débil,
homónimos, vecindarios sin herencia de evidencia, consultas de GHunt frente a
colaboradores, commits, URLs engañosas, procedencia durante deduplicación,
componentes grandes y proyección de expedientes previos por REST/MCP. Las
pruebas de geometría verifican la cercanía relativa y el anclaje exterior;
el script usa Node con soporte nativo de TypeScript.

Validación del 15-10-2026: suite general del backend, 849 pruebas aprobadas
y 16 excluidas por marcadores; integración PostgreSQL/REST/MCP, 14 aprobadas;
suite específica de correlación tras el ajuste final de etiquetas, 23 aprobadas;
geometría del frontend, 4 aprobadas. TypeScript (`tsc --noEmit`) sin errores.
Los esquemas de integración son temporales y no modifican los expedientes reales.
