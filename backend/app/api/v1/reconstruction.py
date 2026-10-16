from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.reconstruction import ReconstructionReport
from app.services.digital_reconstruction import build_reconstruction, get_reconstruction
from app.services import reconstruction_handoff
from app.schemas.reconstruction_handoff import ReconstructionRequestRead

router = APIRouter()


@router.post('/investigations/{id}/reconstruction/build', response_model=ReconstructionReport)
async def build(id: UUID, db: AsyncSession = Depends(get_db)):
    return await build_reconstruction(db, id)


@router.get('/investigations/{id}/reconstruction', response_model=ReconstructionReport)
async def get(id: UUID, db: AsyncSession = Depends(get_db)):
    return await get_reconstruction(db, id)


@router.get('/investigations/{id}/reconstruction/providers')
async def providers(id: UUID):
    return reconstruction_handoff.options()


@router.post('/investigations/{id}/reconstruction/mcp', response_model=ReconstructionRequestRead)
async def request_mcp(id: UUID, db: AsyncSession = Depends(get_db)):
    return await reconstruction_handoff.request_reconstruction(db, id)


@router.get('/investigations/{id}/reconstruction/mcp', response_model=ReconstructionRequestRead | None)
async def get_mcp(id: UUID, db: AsyncSession = Depends(get_db)):
    return await reconstruction_handoff.latest_request(db, id)


@router.post('/investigations/{id}/reconstruction/mcp/{request_id}/cancel', response_model=ReconstructionRequestRead)
async def cancel_mcp(id: UUID, request_id: UUID, db: AsyncSession = Depends(get_db)):
    return await reconstruction_handoff.cancel_request(db, id, request_id)
