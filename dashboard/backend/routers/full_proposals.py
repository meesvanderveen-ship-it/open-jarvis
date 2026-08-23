from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services.full_proposals import get_full_parameter_proposals

router = APIRouter()


@router.get("/api/parameters/proposals/full")
def full_parameter_proposals() -> dict:
    return get_full_parameter_proposals()
