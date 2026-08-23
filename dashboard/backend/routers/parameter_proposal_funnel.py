from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.parameter_proposal_funnel import get_parameter_proposal_funnel
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/parameters/proposal-funnel")
def parameter_proposal_funnel() -> dict:
    try:
        return get_parameter_proposal_funnel()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
