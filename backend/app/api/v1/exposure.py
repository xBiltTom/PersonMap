from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.exposure import ExposureReport
from app.services import exposure_lens


router = APIRouter()


@router.post("/investigations/{id}/exposure/analyze", response_model=ExposureReport)
async def analyze_exposure(id: UUID, db: AsyncSession = Depends(get_db)):
    """Analyze only the finalized ReviewedFootprintDataset for this investigation."""
    return await exposure_lens.analyze(db, id)


@router.get("/investigations/{id}/exposure", response_model=ExposureReport)
async def get_exposure_report(id: UUID, db: AsyncSession = Depends(get_db)):
    """Return the latest saved report and mark it stale when its reviewed input changed."""
    return await exposure_lens.get_report(db, id)
