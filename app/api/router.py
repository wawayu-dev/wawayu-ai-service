from fastapi import APIRouter

from app.capabilities.recruitment_events.router import (
    router as recruitment_event_router,
)
from app.core.config import get_settings

router = APIRouter()
router.include_router(recruitment_event_router)


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name}
