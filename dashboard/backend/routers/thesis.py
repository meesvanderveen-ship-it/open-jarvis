from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services.thesis import get_thesis_report

router = APIRouter()


@router.get("/api/thesis")
def thesis() -> dict:
    return get_thesis_report()
