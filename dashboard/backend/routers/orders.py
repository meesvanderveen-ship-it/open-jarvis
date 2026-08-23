from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.orders import get_orders
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/orders")
def orders() -> dict:
    try:
        return get_orders()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
