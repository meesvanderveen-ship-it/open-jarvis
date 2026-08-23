from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from dashboard.backend.services.trace import get_ticker_trace

router = APIRouter()


@router.get("/api/agents/latest-trace")
def latest_trace(ticker: str = Query(..., min_length=1, max_length=20)) -> dict:
    if not all(c.isalnum() or c in "-_" for c in ticker):
        raise HTTPException(status_code=400, detail="invalid ticker format")
    return get_ticker_trace(ticker.upper())
