# Demo con ngrok

El navegador usa `/api/v1` del mismo origen. Next.js encamina `/api/v1/*`
y `/health` al backend local. Así basta con publicar el puerto 3000 y los
streams SSE pasan por la misma URL. El endpoint MCP sigue en el puerto 8000
local y no tiene un rewrite público.

## Abrir la demo

Verifica primero la rama y la base de datos del `.env` local: `main` usa
`person_map`; la rama Lite usa `personmap_lite` con `PERSONMAP_ENV=lite`.
Los archivos `.env` no cambian al cambiar de rama. Conserva una copia local
antes de ajustar la conexión; no copies la base ni mezcles migraciones de Lite
con las de `main`.

1. Inicia el backend en el puerto 8000 y el frontend en el 3000.
2. Ejecuta:

   ```bash
   ~/.local/bin/ngrok http http://127.0.0.1:3000 --inspect=false
   ```

3. Comparte la URL HTTPS que imprime ngrok. Si aparece la pantalla inicial
   de ngrok, pulsa **Visit Site**.
4. Para desarrollo, agrega el hostname exacto de esa URL a
   `DEV_ALLOWED_ORIGINS` en `frontend/.env.local` y reinicia Next.js si no
   recarga la configuración. Ejemplo:

   ```dotenv
   DEV_ALLOWED_ORIGINS=tu-host.ngrok-free.dev
   ```

Mantén el backend, el frontend y ngrok encendidos durante la presentación.
Para cerrar el túnel, usa Ctrl+C en su terminal.

## Configuración de la API

Sin `NEXT_PUBLIC_API_URL`, el navegador usa el proxy del mismo origen.
Si ya tienes esa variable configurada, usa `NEXT_PUBLIC_API_URL=/api/v1`
para la demo y reinicia el frontend (o reconstruye si usas producción).
No debe apuntar a localhost en el navegador de los visitantes.

`API_PROXY_TARGET` configura el destino interno del proxy; por defecto es
`http://127.0.0.1:8000`. En Docker, configura `http://backend:8000` al construir
el frontend y durante su ejecución.

## Reconstrucción por MCP

Desde la web, crea la solicitud y copia su comando. Ejecútalo en la máquina
que tiene PersonMap y Codex: la conexión MCP sigue usando
`http://127.0.0.1:8000/mcp`, sin modificar el comando por el túnel. El
resultado se publica en el mismo backend y aparece en la web pública.

El authtoken de ngrok se guarda en `~/.config/ngrok/ngrok.yml`; no forma
parte del repositorio. Instalación oficial: https://ngrok.com/download/linux.

## Archivos locales

Las credenciales, los logs, los respaldos de configuración en `.local-runtime/`
y las exportaciones de expedientes en `docs/exportaciones/` se conservan
localmente y están excluidos de Git. El script de exportación es código
reutilizable; sus JSON de salida contienen datos de investigaciones.
