from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.learning_status import get_learning_status
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/status/learning")
def status_learning() -> dict:
    try:
        return get_learning_status()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
