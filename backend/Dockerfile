# =====================================================================
# PersonMap — Backend Dockerfile
# Multi-stage: instala dependencias con uv, copia solo el código
# necesario al stage final. Imagen final ~200 MB vs ~1 GB sin staging.
# =====================================================================

# --- Stage 1: builder ---
FROM python:3.12-slim AS builder

# uv es significativamente más rápido que pip para instalar desde pyproject.toml
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /build

# Copia el manifiesto primero para aprovechar la caché de capas: solo se
# reinstala si cambia pyproject.toml o uv.lock, no en cada cambio de código.
COPY pyproject.toml uv.lock ./

# Instala dependencias en un virtualenv dentro del builder
RUN uv sync --frozen --no-install-project --no-dev

# Copia el código de la aplicación
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# --- Stage 2: runtime ---
FROM python:3.12-slim

# Metadatos para trazabilidad
LABEL org.opencontainers.image.title="PersonMap Backend"
LABEL org.opencontainers.image.description="OSINT footprint audit platform — FastAPI backend"

# Public PDF publications are read locally without OCR or external services.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*

# Usuario no-root para reducir la superficie de ataque
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Copia el virtualenv y el código del builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/app /app/app
COPY --from=builder /build/migrations /app/migrations
COPY --from=builder /build/alembic.ini /app/alembic.ini

# El virtualenv del builder ya tiene el interprete correcto; lo activamos
# añadiéndolo al PATH para que uvicorn sea el ejecutable predeterminado.
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

# Las migraciones se aplican en el entrypoint del compose para poder
# usar `depends_on: condition: service_healthy` con PostgreSQL.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
