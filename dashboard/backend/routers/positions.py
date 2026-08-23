from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services.positions import get_positions

router = APIRouter()


@router.get("/api/positions")
def positions() -> dict:
    return get_positions()
