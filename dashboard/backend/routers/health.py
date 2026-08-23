from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "read_only": True,
        "writes_enabled": False,
        "coinbase_calls_enabled": False,
    }
