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
    yield


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
