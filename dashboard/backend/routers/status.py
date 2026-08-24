from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.live_status import get_live_status
from dashboard.backend.services.pipeline_health import get_pipeline_health
from dashboard.backend.services.shell_tool import ToolExecutionError
from dashboard.backend.services.ticker_universe import get_allowed_tickers

router = APIRouter()


@router.get("/api/status/live")
def status_live() -> dict:
    try:
        return get_live_status()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/status/tickers")
def status_tickers() -> dict:
    return {"allowed_tickers": get_allowed_tickers()}


@router.get("/api/status/pipeline")
def status_pipeline() -> dict:
    try:
        return get_pipeline_health()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
