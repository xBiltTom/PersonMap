from fastapi import APIRouter
from app.api.v1.investigations import router as investigations_router
from app.api.v1.graph import router as graph_router
from app.api.v1.identity import router as identity_router
from app.api.v1.stream import router as stream_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.surveys import router as surveys_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(investigations_router, tags=["Investigations"])
api_v1_router.include_router(graph_router, tags=["Graph"])
api_v1_router.include_router(identity_router, tags=["Identity"])
api_v1_router.include_router(stream_router, tags=["Stream"])
api_v1_router.include_router(metrics_router, tags=["Metrics"])
api_v1_router.include_router(surveys_router, tags=["Surveys"])
