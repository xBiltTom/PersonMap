import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    _warn_if_multiple_workers()
    yield


def _warn_if_multiple_workers() -> None:
    """
    Avisa si el servidor corre con más de un worker.

    El EventBus que alimenta la consola en vivo vive en memoria del proceso: con
    varios workers, el que atiende el stream SSE puede no ser el que ejecuta la
    investigación, y la consola se queda muda sin ningún error visible. Escalar
    horizontalmente exige antes mover el bus a Redis u otro pub/sub externo.
    """
    workers = os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS")
    try:
        if workers and int(workers) > 1:
            logging.getLogger("uvicorn.error").warning(
                "PERSON-MAP: detectados %s workers. El bus de eventos SSE es "
                "in-process, por lo que la consola en vivo perdera eventos. "
                "Usa un solo worker o migra el EventBus a un pub/sub externo.",
                workers,
            )
    except ValueError:
        pass


app = FastAPI(
    title="Person Map OSINT API",
    description=(
        "Plataforma de inteligencia de fuentes abiertas (OSINT) y concientización "
        "de huella digital con agente IA opcional y orquestador heurístico."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows local dev from Next.js (port 3000)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "person-map-backend",
        "ai_enabled": settings.ai_enabled,
        "llm_model": settings.llm_model if settings.ai_enabled else None,
    }
