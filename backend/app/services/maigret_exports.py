"""Read-only exports of native detections already persisted in a dossier."""
from importlib.util import find_spec

from fastapi import HTTPException
from sqlalchemy import select

from app.models.entity import Entity
from app.models.investigation import Investigation
from app.tools.maigret_reports import REPORT_TYPES, report_record, check_records
from app.tools.maigret_runner import run_maigret


async def export_maigret(investigation_id, report_format, db):
    investigation = await db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(404, "Investigación no encontrada")
    if report_format not in REPORT_TYPES:
        raise HTTPException(422, "Formato de informe no disponible")
    if report_format == "pdf" and not find_spec("xhtml2pdf"):
        raise HTTPException(501, "Instala las dependencias maigret[pdf] del proyecto para exportar PDF")
    entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == investigation_id))).all())
    runtime = {**(investigation.metrics or {}).get("collection_runtime", {}),
               **(investigation.metrics or {}).get("external_runtime", {})}
    records = [*check_records(runtime), *[record for entity in entities if (record := report_record(entity)) is not None]]
    if not records:
        raise HTTPException(409, "La investigación aún no tiene detecciones nativas de Maigret")
    result = {}
    async def collected(value):
        result.update(value)
    try:
        await run_maigret("", [], {}, collected, operation="report", records=records, report_format=report_format)
    except RuntimeError as exc:
        raise HTTPException(503, "El generador de informes Maigret no pudo completar la exportación") from exc
    return result
