from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from dashboard.backend.security.safe_paths import UnsafePathError
from dashboard.backend.services.logs import list_available_logs, tail_log

router = APIRouter()


@router.get("/api/logs")
def logs(
    type: str | None = Query(default=None, max_length=200),
    ticker: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    available = list_available_logs()
    if not type:
        return {"available_logs": available, "entries": []}

    if not type.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="type must be a .jsonl filename")

    try:
        result = tail_log(type, limit=limit, ticker=ticker, q=q)
    except UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"available_logs": available, **result}
