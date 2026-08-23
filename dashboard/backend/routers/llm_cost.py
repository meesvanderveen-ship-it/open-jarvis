from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.backend.services.llm_cost import (
    get_llm_cost_24h,
    get_llm_cost_7d,
    get_multi_agent_prompt_audit,
)
from dashboard.backend.services.shell_tool import ToolExecutionError

router = APIRouter()


@router.get("/api/llm/cost")
def llm_cost_24h() -> dict:
    try:
        return get_llm_cost_24h()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/llm/cost/7d")
def llm_cost_7d() -> dict:
    try:
        return get_llm_cost_7d()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/llm/multi-agent-audit")
def multi_agent_prompt_audit() -> dict:
    try:
        return get_multi_agent_prompt_audit()
    except ToolExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
