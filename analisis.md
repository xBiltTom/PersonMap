Para el proyecto que hemos definido —**OSINT + agente IA adaptativo + correlación de identidad + grafo de huella digital + análisis de exposición**— yo NO haría un monolito gigante. Haría una arquitectura modular, pero sin caer todavía en microservicios innecesarios.

## 🧠 Arquitectura que te recomiendo

La resumiría así:

```text
                         ┌──────────────────────┐
                         │      Next.js         │
                         │   Web / Dashboard     │
                         └──────────┬───────────┘
                                    │
                              REST / WebSocket
                                    │
                         ┌──────────▼───────────┐
                         │      FastAPI         │
                         │    API Gateway       │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    │                                │
             ┌──────▼──────┐                  ┌──────▼──────┐
             │ Investigation│                  │    Auth     │
             │   Manager    │                  │ / Users     │
             └──────┬──────┘                  └─────────────┘
                    │
             ┌──────▼─────────────────────────────────┐
             │          AI OSINT AGENT                 │
             │                                         │
             │  Context → Plan → Tool → Evidence       │
             │       ↑                  ↓              │
             │       └──── Replanning ──┘              │
             └──────┬─────────────────────────────────┘
                    │
       ┌────────────┼───────────────┐
       │            │               │
 ┌─────▼─────┐ ┌────▼─────┐ ┌─────▼────────┐
 │ OSINT     │ │ Search    │ │ Specialized  │
 │ Engines   │ │ Providers │ │ APIs         │
 └─────┬─────┘ └────┬─────┘ └─────┬────────┘
       │             │             │
       └─────────────┼─────────────┘
                     │
              ┌──────▼──────┐
              │ Normalizer  │
              │ / Evidence  │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │ Correlation │
              │ + Identity  │
              │ Resolution  │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │ Graph Model │
              │ + Risk      │
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │ PostgreSQL  │
              └─────────────┘
```

Y hay una decisión importante:

> **El agente NO debería ser quien directamente haga todo.**

El agente decide **qué hacer**. Una capa de herramientas/policies decide **qué está permitido ejecutar**.

Eso te da mucha más robustez y, encima, queda muy bonito para defenderlo académicamente.

---

# 🐍 1. Backend: Python + FastAPI

Aquí sí, Python es prácticamente obligatorio para nuestro caso.

### Stack

* **Python 3.13+**
* **FastAPI**
* **Pydantic**
* **SQLAlchemy 2**
* **Alembic**
* **httpx**
* **asyncio**
* **WebSockets**

FastAPI sería nuestra API principal.

Por ejemplo:

```text
POST /investigations
GET  /investigations/{id}
GET  /investigations/{id}/graph
GET  /investigations/{id}/evidence
GET  /investigations/{id}/events
```

Y WebSocket para que el frontend pueda ver:

```text
Agent started investigation
      ↓
Searching GitHub
      ↓
Found username
      ↓
Found personal website
      ↓
Possible email correlation
      ↓
Confidence: 87%
      ↓
Searching additional sources...
```

Eso en vivo sería **BRUTAL visualmente** xd.

---

# 🤖 2. El cerebro: agente OSINT

Aquí está una de las partes más interesantes.

Yo utilizaría:

### **LangGraph**

Porque nuestro agente no es simplemente:

```text
pregunta → LLM → respuesta
```

Tenemos un flujo cíclico:

```text
              ┌──────────────┐
              │ Target Input │
              └──────┬───────┘
                     ↓
                ┌─────────┐
                │ Planner │
                └────┬────┘
                     ↓
                Select Tool
                     ↓
                 Execute
                     ↓
                Evidence
                     ↓
             Update Knowledge
                     ↓
            ┌────────────────┐
            │ Replan needed? │
            └───────┬────────┘
                 YES│
                     └──────────────→ Planner
                 
                 NO
                  ↓
             Final Analysis
```

Eso es justamente un **agente con estado y ciclos**, donde LangGraph encaja muchísimo mejor que hacer un simple agente con un `while`.

---

# 🧩 3. Sistema de herramientas

Esta sería probablemente **la parte más importante de todo el backend**.

No quiero que nuestro agente conozca directamente 50 APIs.

Quiero una interfaz común:

```python
class OSINTTool:
    name: str

    async def execute(
        self,
        target: Target
    ) -> ToolResult:
        ...
```

Entonces podemos tener:

```text
tools/
├── github/
├── search/
├── username/
├── email/
├── domains/
├── social/
├── breach/
├── metadata/
└── websites/
```

Cada herramienta devuelve un formato común.

Por ejemplo:

```json
{
  "source": "github",
  "entity": {
    "type": "account",
    "username": "example"
  },
  "evidence": [],
  "confidence": 0.94
}
```

Así podemos conectar:

* herramientas propias
* APIs externas
* proyectos open source
* herramientas ejecutadas como subprocess
* servicios especializados

sin que el agente tenga que preocuparse por cómo funciona internamente cada una.

---

# 🔥 4. Aquí entra nuestra idea de reutilizar otros proyectos OSINT

Esto es precisamente donde **no debemos reinventar la rueda**.

Podemos tener:

```text
OSINT Provider Layer

 ├── SpiderFoot adapter
 ├── Sherlock adapter
 ├── Maigret adapter
 ├── theHarvester adapter
 ├── custom search adapter
 ├── GitHub API
 ├── Have I Been Pwned API
 └── etc.
```

Pero **no necesariamente todos**.

La filosofía sería:

> "Utilizamos los mejores motores disponibles para cada tipo de evidencia y construimos encima la capa que ellos no resuelven."

Eso nos deja concentrarnos en:

**Agent + correlation + identity resolution + graph + exposure analysis.**

Y no pasar seis meses reimplementando buscadores de usernames xd.

---

# 🧠 5. Identity Resolution

Esta es otra parte que yo convertiría en componente independiente.

Porque encontrar:

```text
username = bilton123
```

no significa automáticamente:

```text
bilton123 = Persona X
```

Necesitamos evaluar evidencias.

Por ejemplo:

```text
GitHub
   │
   ├── username: bilton123
   ├── website: bilton.dev
   └── email: x@domain.com
             │
             ▼
        Personal Website
             │
             ├── same name
             ├── same GitHub
             └── same university
```

Entonces:

```text
Identity confidence = 0.93
```

Podríamos utilizar inicialmente un modelo de scoring:

```text
+ username match
+ email match
+ website cross-link
+ name match
+ bio similarity
+ organization match
--------------------------------
             ↓
        confidence
```

Y posteriormente experimentar con modelos más sofisticados.

Esto además es **muy investigable**.

---

# 🕸️ 6. Grafo: probablemente Neo4j... pero NO de entrada

Aquí te haría una recomendación importante.

Inicialmente:

### PostgreSQL + JSONB

puede almacenar perfectamente nuestras entidades y relaciones.

Por ejemplo:

```text
investigations
entities
relationships
evidence
sources
agent_events
```

Y las relaciones:

```text
entity A
    ↓
relationship
    ↓
entity B
```

Pero...

Si el grafo crece bastante, podemos incorporar:

### Neo4j

como **motor especializado de grafos**.

Arquitectura:

```text
             PostgreSQL
          metadata / users
                 │
                 │
                 ▼
             Graph Layer
                 │
                 ▼
              Neo4j
```

Aunque para el MVP yo empezaría solamente con PostgreSQL.

No necesitamos meter Neo4j porque "se ve hacker" xd.

---

# 🎨 7. Frontend

Aquí yo me quedaría con algo que ya manejas:

### Next.js + React + TypeScript

Stack:

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
```

Y para el grafo:

### React Flow

Es probablemente mi primera opción para el MVP.

Nos permite hacer:

```text
                ┌─────────────┐
                │   PERSON    │
                └──────┬──────┘
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
     GitHub         LinkedIn       Website
        │              │              │
        ↓              ↓              ↓
    Projects        Education       Email
```

Y luego podemos hacer cosas más avanzadas con D3.js si necesitamos visualizaciones específicas.

---

# 🖥️ 8. El dashboard

Yo lo diseñaría tipo **centro de investigación**.

Algo así conceptualmente:

```text
┌─────────────────────────────────────────────────────────────┐
│ OSINT // INVESTIGATION #001                   ● RUNNING     │
├─────────────┬─────────────────────────────────┬─────────────┤
│             │                                 │             │
│ TARGET      │                                 │ EXPOSURE    │
│             │          GRAPH                  │             │
│ Name        │                                 │             │
│ Username    │       ●───●────●               │   73/100    │
│ Email       │      /    │     │               │             │
│ Context     │     ●     ●     ●              │ Identity    │
│             │           │                    │ Accounts    │
│             │           ●                    │ Metadata    │
│             │                                 │             │
├─────────────┴─────────────────────────────────┴─────────────┤
│ AGENT ACTIVITY                                               │
│ ✓ GitHub search                              1.2s            │
│ ✓ Website discovered                         0.8s            │
│ ✓ Identity correlation                       0.4s            │
│ → Investigating LinkedIn...                  ...             │
└─────────────────────────────────────────────────────────────┘
```

Esto puede quedar **muy potente para la demo**.

---

# 🗄️ 9. PostgreSQL

PostgreSQL sería nuestra DB principal.

Yo propondría algo así:

```text
users
roles
profiles

investigations
targets

entities
entity_attributes

relationships

sources
evidence

agent_runs
agent_events

risk_assessments
reports
```

Y usaría:

### PostgreSQL + JSONB

para almacenar respuestas heterogéneas de las herramientas.

Ejemplo:

```text
evidence
---------
id
source
type
raw_data JSONB
normalized_data JSONB
timestamp
confidence
```

Esto es importante porque cada OSINT tool devuelve cosas diferentes.

---

# 🔎 10. Search layer

Aquí tenemos varias posibilidades.

Podemos tener:

```text
SearchProvider
     │
     ├── Google/Bing compatible API
     ├── Brave Search API
     ├── SerpAPI
     └── custom search
```

Pero **no quiero que el agente dependa de un proveedor concreto**.

Otra vez:

```python
class SearchProvider:
    async def search(query: str) -> list[SearchResult]:
        ...
```

Y podemos cambiar de proveedor.

---

# ⚡ 11. Redis

Aquí sí metería Redis.

Principalmente para:

* cache
* jobs
* rate limiting
* estado temporal
* coordinación

Y junto con:

### Celery / Dramatiq / ARQ

Yo probablemente elegiría **ARQ** porque estamos en Python async.

Por ejemplo:

```text
FastAPI
   │
   ├── creates investigation
   │
   ▼
Redis Queue
   │
   ▼
OSINT Worker
   │
   ├── GitHub
   ├── Search
   ├── Username
   └── ...
```

Esto evita bloquear FastAPI mientras el agente está haciendo una investigación de 3 minutos.

---

# 🐳 12. Docker

**Docker Compose de una.**

Nuestro entorno podría ser:

```text
docker-compose.yml

services:

  frontend:
    Next.js

  backend:
    FastAPI

  worker:
    OSINT Worker

  postgres:
    PostgreSQL

  redis:
    Redis
```

Y si posteriormente metemos Neo4j:

```text
  neo4j:
    Neo4j
```

---

# 🧪 13. Testing

Para una investigación académica esto es importante.

### Backend

```text
pytest
pytest-asyncio
httpx
```

### Frontend

```text
Vitest
Testing Library
Playwright
```

### Agent

Aquí necesitamos tests bastante interesantes.

Por ejemplo:

```text
Target A
Expected:
    GitHub
    LinkedIn
    Website

Agent:
    GitHub
    Website
    LinkedIn

Coverage = 100%
```

Y comparar:

```text
Rule-based Agent
vs
Adaptive Agent
```

🔥 **Ahí empieza a aparecer la parte científica del proyecto.**

---

# 📊 14. Métricas

Nuestro sistema debería guardar datos suficientes para calcular:

### Cobertura

```text
discovered relevant entities
----------------------------
expected relevant entities
```

### Precision de relaciones

```text
correct relationships
---------------------
all inferred relationships
```

### False positives

```text
incorrect correlations
----------------------
all correlations
```

### Eficiencia

```text
time
number of tool calls
number of redundant searches
```

### Adaptabilidad

Podemos registrar:

```text
tool selection sequence
```

y analizar si el agente realmente adapta su estrategia al contexto.

---

# 🛡️ 15. Security / Ethics layer

Esto **sí o sí** lo metería en arquitectura.

```text
                 AI Agent
                    │
                    ▼
             Policy Engine
                    │
          ┌─────────┴─────────┐
          │                   │
       ALLOWED             BLOCKED
          │                   │
          ▼                   ▼
      OSINT Tools         Restricted
```

Y además:

```text
Investigation
     │
     ├── authorization
     ├── consent
     ├── audit log
     ├── source tracking
     └── evidence provenance
```

Especialmente porque nuestro estudio sería con estudiantes.

La regla debería ser:

> **La plataforma analiza información públicamente accesible y, para la investigación, únicamente objetivos con autorización explícita.**

---

# 🧱 Stack completo

Entonces, si hoy tuviera que congelar el stack:

| Capa              | Tecnología                                     |
| ----------------- | ---------------------------------------------- |
| Frontend          | **Next.js + React + TypeScript**               |
| UI                | **Tailwind + shadcn/ui**                       |
| Graph UI          | **React Flow**                                 |
| Backend           | **Python + FastAPI**                           |
| Agent             | **LangGraph**                                  |
| LLM               | API de un modelo compatible                    |
| Validation        | **Pydantic**                                   |
| ORM               | **SQLAlchemy**                                 |
| Migrations        | **Alembic**                                    |
| DB                | **PostgreSQL**                                 |
| Cache/Queue       | **Redis**                                      |
| Workers           | **ARQ**                                        |
| HTTP              | **httpx**                                      |
| OSINT integration | **Adapters/Providers**                         |
| Graph DB          | **PostgreSQL inicialmente → Neo4j opcional**   |
| Auth              | **JWT/OAuth2**                                 |
| Testing           | **Pytest + Playwright + Vitest**               |
| Deployment        | **Docker Compose**                             |
| Reverse proxy     | **Caddy/Nginx**                                |
| Reports           | **WeasyPrint / python-docx / openpyxl**        |
| Observability     | **OpenTelemetry + Grafana** *(fase posterior)* |

---

# 🚀 Pero la clave: NO hagamos todo de golpe

Yo lo dividiría en **4 fases**.

### Fase 1 — MVP OSINT

```text
Next.js
   ↓
FastAPI
   ↓
Tools
   ↓
PostgreSQL
```

Input:

```text
username/email/name
```

Output:

```text
entities + evidence + relationships
```

---

### Fase 2 — Agent

Metemos:

```text
LangGraph
    ↓
Planner
    ↓
Tool selection
    ↓
Evidence
    ↓
Replanning
```

Aquí empieza nuestro **OSINT adaptativo**.

---

### Fase 3 — Identity Graph

Construimos:

```text
PERSON
 ├── ACCOUNT
 ├── WEBSITE
 ├── EMAIL
 ├── ORGANIZATION
 ├── ACTIVITY
 └── ATTRIBUTE
```

con:

```text
confidence
source
timestamp
evidence
```

Y el dashboard empieza a ponerse enfermo xd.

---

### Fase 4 — Investigación

Aquí hacemos la parte que puede convertir el proyecto en **paper**, no solamente en software:

```text
                 ┌──────────────────┐
                 │ Rule-based OSINT  │
                 └────────┬─────────┘
                          │
                    Experiment
                          │
                 ┌────────▼─────────┐
                 │ Agentic OSINT    │
                 └────────┬─────────┘
                          │
              Compare coverage,
          precision, time, relevance
                          │
                          ▼
                 Digital Footprint
                      Visualization
                          │
                          ▼
                 Awareness pre/post
```

Y ahí tenemos **dos experimentos potenciales en uno**:

1. **¿El agente adaptativo reconstruye mejor la identidad digital que una estrategia basada en reglas?**
2. **¿Mostrar al estudiante su propia huella digital reconstruida mejora su conciencia de seguridad y privacidad?**

Eso, bro, ya no es simplemente *"hicimos una página con IA que busca personas"*.

Es un sistema con una **arquitectura investigable**, una **comparación experimental** y una **intervención medible**.

Y honestamente, yo arrancaría el repo directamente con esta estructura:

```text
osint-agent/
├── apps/
│   ├── web/                 # Next.js
│   └── api/                 # FastAPI
│
├── packages/
│   └── shared/
│
├── services/
│   ├── agent/
│   ├── osint/
│   ├── identity/
│   ├── correlation/
│   ├── graph/
│   └── risk/
│
├── infrastructure/
│   ├── docker/
│   └── postgres/
│
├── tests/
│
├── docs/
│
└── docker-compose.yml
```

**Ese sería nuestro punto de partida.** Y además encaja bastante bien con lo que ya vienes trabajando de FastAPI/Next/Postgres, así que no estaríamos aprendiendo 17 tecnologías nuevas simultáneamente. xd
