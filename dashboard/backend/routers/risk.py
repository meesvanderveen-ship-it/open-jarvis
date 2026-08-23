from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.risk_guards import get_risk_guards
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/risk/guards")
def risk_guards() -> dict:
    try:
        return get_risk_guards()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
