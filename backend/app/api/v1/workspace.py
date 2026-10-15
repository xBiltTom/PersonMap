"""Web access to authored analysis; agent operations are exposed through MCP."""
from uuid import UUID
import base64
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.workspace import NoteCreate, NoteRead
from app.services.workspace import workspace
from app.core.database import get_db
from app.services.maigret_exports import export_maigret
from app.tools.maigret_reports import ReportFormat
from app.tools.maigret_catalog import capabilities

router = APIRouter()


@router.get("/email-enumerator/capabilities")
def email_enumerator_capabilities():
    from app.tools.email_catalog import capabilities as email_info
    return email_info()


@router.get("/ghunt/capabilities")
def ghunt_capabilities():
    from app.tools.ghunt_runtime import capabilities as ghunt_info
    return ghunt_info()


@router.get("/maigret/capabilities")
def maigret_capabilities():
    return capabilities()


@router.get("/investigations/{id}/maigret/report")
async def download_maigret_report(id: UUID, format: ReportFormat = "json", db: AsyncSession = Depends(get_db)):
    exported = await export_maigret(id, format, db)
    return Response(base64.b64decode(exported["body"]), media_type=exported["mime_type"], headers={
        "Content-Disposition": f'attachment; filename="maigret-{id}.{exported["extension"]}"',
        "X-PersonMap-Scope": exported["scope"], "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:"})


@router.post("/investigations/{id}/notes", response_model=NoteRead, status_code=201)
async def add_analyst_note(id: UUID, payload: NoteCreate):
    return await workspace.add_note(id, payload)
