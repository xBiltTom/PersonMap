"""Web access to authored analysis; agent operations are exposed through MCP."""
from uuid import UUID
from fastapi import APIRouter

from app.schemas.workspace import NoteCreate, NoteRead
from app.services.workspace import workspace

router = APIRouter()


@router.post("/investigations/{id}/notes", response_model=NoteRead, status_code=201)
async def add_analyst_note(id: UUID, payload: NoteCreate):
    return await workspace.add_note(id, payload)
