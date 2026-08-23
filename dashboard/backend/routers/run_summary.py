from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.run_summary import get_run_summary
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/status/run-summary")
def status_run_summary() -> dict:
    try:
        return get_run_summary()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
