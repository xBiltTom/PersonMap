# PERSON-MAP 🔍 // Plataforma OSINT de Mapa de Evidencia y Huella Digital

Plataforma forense de inteligencia de fuentes abiertas (OSINT) diseñada para el análisis de exposición digital y concientización sobre ingeniería social en estudiantes universitarios.

---

## Características Principales

- **Mínimo 1 dato de entrada**: Puedes iniciar una consulta con un solo identificador (nombre completo, correo, nombre de usuario / alias, teléfono o DNI). El motor pivotea desde esos datos y registra las fuentes de cada observación.
- **Funciona 100% sin IA**: Cuenta con un **orquestador heurístico por código** (`rule_engine.py`) con detección automática de pivotes (nuevos correos descubiertos, alias en biografías, perfiles candidatos) y resolución multivariable.
- **Potenciado por IA (Agnóstico vía LiteLLM)**: Puedes conectar cualquier modelo compatible con function calling (`Gemini`, `Groq`, `OpenAI`, `Ollama`, etc.) configurando `LLM_MODEL` y `LLM_API_KEY` en `.env`.
- **Comprobación Profunda (OpenGraph & extracción de metadatos)**: Extrae datos públicos de perfiles (`og:title`, `og:description`, `og:image`) y conserva su procedencia.
- **Mapa de Evidencia**: Agrupa visualmente observaciones conectadas por correos declarados, enlaces explícitos y otros hechos inspeccionables, sin atribuirlas a una persona.
- **Visualizaciones Forenses**:
  - **Mapa Digital Interactivo (React Flow)** con nodos por categoría y aristas de evidencia inspeccionable.
  - **Línea de Tiempo Cronológica** de descubrimientos.
  - **Consola en Tiempo Real (SSE)** para observar el flujo de trabajo en vivo.
  - **Tabla de Hallazgos** con filtros por categoría y enlaces de evidencia directa.

---

## Estructura del Repositorio

```text
person-map/
├── backend/                  # API REST + Motor OSINT + Agente IA
│   ├── app/
│   │   ├── api/v1/           # Endpoints: investigations, graph, identity, stream
│   │   ├── core/             # Configuración (.env), Base de datos (asyncpg), EventBus SSE
│   │   ├── models/           # SQLAlchemy ORM (targets, investigations, entities, relationships, clusters)
│   │   ├── schemas/          # Validación Pydantic v2
│   │   ├── tools/            # Módulos OSINT puros (username, email, social_verifier, dorks, academic, DNI)
│   │   ├── identity/         # Algoritmo de scoring, clusters de identidad y cálculo de riesgo
│   │   ├── engine/           # Orquestador maestro y motor de pivoteo heurístico
│   │   └── agent/            # Wrapper agnóstico LiteLLM y analista IA
│   └── tests/                # Suite de pruebas automatizadas con pytest
│
├── frontend/                 # Dashboard Next.js (App Router, Tailwind CSS, React Flow)
│   └── src/
│       ├── app/              # Páginas: Landing (/) y Expediente (/investigation/[id])
│       ├── components/       # Componentes: Graph, Identity, Findings, Console, Timeline, Report
│       └── lib/              # Cliente API y tipos TypeScript
│
├── .env.example              # Variables de entorno
└── README.md
```

---

## Guía de Ejecución Local

### 1. Requisitos Previos
- PostgreSQL (16+) activo en `localhost:5432`.
- `uv` instalado para el backend Python (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- `pnpm` y Node.js (v20+) para el frontend.

### 2. Base de Datos
La base de datos `person_map` se crea con:
```bash
createdb -U postgres person_map
# o con psql:
psql -U postgres -c "CREATE DATABASE person_map;"
```
*(Las tablas se inicializan automáticamente al levantar el backend)*.

### 3. Levantar el Backend (FastAPI)
```bash
cd backend
# Ejecutar el servidor con uv
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
La documentación interactiva OpenAPI estará en: `http://localhost:8000/docs`.

### 4. Levantar el Frontend (Next.js)
En otra terminal:
```bash
cd frontend
pnpm dev
```
Abre en tu navegador: `http://localhost:3000`.

### 5. Correr las Pruebas del Backend
```bash
cd backend
uv run pytest
```
