from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services.prompts import get_prompts

router = APIRouter()


@router.get("/api/prompts")
def prompts() -> dict:
    return get_prompts()
