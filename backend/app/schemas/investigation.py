from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.schemas.target import TargetCreate, TargetRead
from app.schemas.entity import EntityRead
from app.schemas.identity import IdentityClusterRead


# Estrategias de orquestación seleccionables. `hybrid` se añadió en la Fase 3
# como TERCERA condición, sin sustituir a las dos anteriores: `rules` y
# `agentic` deben seguir siendo brazos experimentales independientes para que la
# comparativa del artículo tenga sentido.
#
#   auto       → agente si hay LLM configurado; si no, motor de reglas
#   rule_based → motor heurístico determinista, sin IA
#   agentic    → agente autónomo IA (planifica y despacha todo)
#   hybrid     → barrido heurístico completo + refinamiento IA de los huecos
Strategy = Literal["auto", "rule_based", "agentic", "hybrid"]


class InvestigationCreate(BaseModel):
    target: TargetCreate
    # Se valida como enumeración cerrada: antes era un `str` libre, de modo que
    # una errata ("agentico", "hybird") se aceptaba con HTTP 201 y la
    # investigación caía silenciosamente al motor de reglas, contaminando la
    # muestra del artículo con una condición experimental equivocada.
    strategy: Strategy = "auto"


class InvestigationRead(BaseModel):
    id: UUID
    target_id: UUID
    strategy: str
    status: str
    risk_score: int
    summary: Optional[str] = None
    metrics: Dict[str, Any] = {}
    created_at: datetime
    completed_at: Optional[datetime] = None
    target: Optional[TargetRead] = None

    model_config = ConfigDict(from_attributes=True)


class InvestigationDetail(InvestigationRead):
    entities: List[EntityRead] = []
    identity_clusters: List[IdentityClusterRead] = []
