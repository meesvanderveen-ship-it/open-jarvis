from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.learning_intelligence import get_learning_intelligence
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/learning/intelligence")
def learning_intelligence() -> dict:
    try:
        return get_learning_intelligence()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
