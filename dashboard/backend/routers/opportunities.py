from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services.opportunities import get_opportunities

router = APIRouter()


@router.get("/api/opportunities/latest")
def opportunities_latest() -> dict:
    return get_opportunities()
