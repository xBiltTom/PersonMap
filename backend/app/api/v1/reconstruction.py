from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.reconstruction import ReconstructionReport
from app.services.digital_reconstruction import build_reconstruction, get_reconstruction

router = APIRouter()


@router.post('/investigations/{id}/reconstruction/build', response_model=ReconstructionReport)
async def build(id: UUID, db: AsyncSession = Depends(get_db)):
    return await build_reconstruction(db, id)


@router.get('/investigations/{id}/reconstruction', response_model=ReconstructionReport)
async def get(id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_reconstruction(db, id)
