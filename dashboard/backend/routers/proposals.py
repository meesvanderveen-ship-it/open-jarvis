from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.proposals import get_parameter_proposals
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/parameters/proposals")
def parameter_proposals() -> dict:
    try:
        return get_parameter_proposals()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
