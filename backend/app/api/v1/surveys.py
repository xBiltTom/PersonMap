from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.investigation import Investigation
from app.models.survey import AwarenessSurvey
from app.schemas.survey import AwarenessSurveyCreate, AwarenessSurveyRead

router = APIRouter(prefix="/surveys", tags=["Surveys"])


@router.post("", response_model=AwarenessSurveyRead, status_code=201)
async def submit_survey(
    payload: AwarenessSurveyCreate,
    db: AsyncSession = Depends(get_db),
):
    # Sin esta comprobación, una investigation_id inexistente reventaba como
    # IntegrityError de la clave foránea y el cliente recibía un 500 opaco.
    exists = await db.get(Investigation, payload.investigation_id)
    if not exists:
        raise HTTPException(
            status_code=404,
            detail="La investigación indicada no existe; no se puede asociar la encuesta.",
        )

    survey = AwarenessSurvey(
        investigation_id=payload.investigation_id,
        pre_awareness=payload.pre_awareness,
        post_awareness=payload.post_awareness,
        reused_alias=payload.reused_alias,
        knew_commit_leak=payload.knew_commit_leak,
        will_change_habits=payload.will_change_habits,
    )
    db.add(survey)
    await db.commit()
    await db.refresh(survey)
    return survey


@router.get("/stats")
async def get_survey_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Returns aggregated survey statistics for the scientific paper.
    Calculates pre vs post awareness delta and behavioral metrics.
    """
    stmt = select(AwarenessSurvey)
    result = await db.execute(stmt)
    surveys = result.scalars().all()

    total = len(surveys)
    if total == 0:
        return {
            "total_responses": 0,
            "avg_pre_awareness": 0.0,
            "avg_post_awareness": 0.0,
            "delta_awareness": 0.0,
            "reused_alias_pct": 0.0,
            "ignorant_commit_leak_pct": 0.0,
            "will_change_habits_pct": 0.0,
        }

    avg_pre = sum(s.pre_awareness for s in surveys) / total
    avg_post = sum(s.post_awareness for s in surveys) / total
    reused_pct = (sum(1 for s in surveys if s.reused_alias) / total) * 100
    leak_ignorant_pct = (sum(1 for s in surveys if not s.knew_commit_leak) / total) * 100
    change_pct = (sum(1 for s in surveys if s.will_change_habits) / total) * 100

    return {
        "total_responses": total,
        "avg_pre_awareness": round(avg_pre, 2),
        "avg_post_awareness": round(avg_post, 2),
        "delta_awareness": round(avg_post - avg_pre, 2),
        "reused_alias_pct": round(reused_pct, 1),
        "ignorant_commit_leak_pct": round(leak_ignorant_pct, 1),
        "will_change_habits_pct": round(change_pct, 1),
    }
