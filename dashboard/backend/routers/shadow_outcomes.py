from __future__ import annotations

from fastapi import APIRouter, Query

from dashboard.backend.services.shadow_outcomes import (
    get_shadow_outcomes_coverage,
    get_shadow_outcomes_patterns,
    get_shadow_outcomes_recent,
    get_shadow_outcomes_status,
)

router = APIRouter()


@router.get("/api/shadow-outcomes/status")
def shadow_outcomes_status() -> dict:
    return get_shadow_outcomes_status()


@router.get("/api/shadow-outcomes/recent")
def shadow_outcomes_recent(limit: int = Query(default=20, ge=1, le=200)) -> dict:
    return get_shadow_outcomes_recent(limit=limit)


@router.get("/api/shadow-outcomes/coverage")
def shadow_outcomes_coverage() -> dict:
    return get_shadow_outcomes_coverage()


@router.get("/api/shadow-outcomes/patterns")
def shadow_outcomes_patterns() -> dict:
    return get_shadow_outcomes_patterns()
