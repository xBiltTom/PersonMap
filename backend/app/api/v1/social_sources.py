from fastapi import APIRouter

from app.social.capabilities import capabilities

router = APIRouter()


@router.get("/sources/social", response_model=dict)
async def social_source_capabilities():
    """Read-only capability/policy matrix. Does not contact Apify or expose credentials."""
    return capabilities()
