"""Read-only LLM/API cost & usage ledger.

Appends one redacted metadata line per LLM call attempt to
``logs/llm_cost_ledger.jsonl``. This module never logs prompt or completion
*content* — only call metadata (timestamps, token counts, latency, a
allow-listed decision label, and an estimated cost). It never mutates
trading state, never calls Coinbase, and never changes any LLM call
behavior; it is purely an observability side-channel called from
``bot/llm_clients.py`` after each provider attempt.
"""

from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOGS_DIR = Path("logs")
LEDGER_PATH = LOGS_DIR / "llm_cost_ledger.jsonl"

_write_lock = threading.Lock()
_local = threading.local()

# Maps the `stage=` value passed at each bot/llm_clients.py call site to a
# human-readable agent/layer name for cost-breakdown grouping. Anything not
# listed here falls back to the raw stage string (see record_llm_call).
STAGE_TO_AGENT: Dict[str, str] = {
    "entry_gate": "entry_gate",
    "deepseek_preprocess": "deepseek_gate",
    "regime": "analyst_regime",
    "trend": "analyst_trend",
    "breakout": "analyst_breakout",
    "meanrev": "analyst_meanrev",
    "bull": "analyst_bull",
    "bear": "analyst_bear",
    "synth": "analyst_synth",
    "trade_planner_gpt_5_5": "trade_planner",
    "judge_gpt_5_5": "final_judge",
    "judge_anthropic_fallback": "final_judge_fallback",
    "position_watch": "position_watch",
    "execution_planner_read_only": "execution_planner",
    "real_fresh_phase_c_judge": "offline_review_judge",
}

# Decision labels we are willing to persist verbatim. Anything else collapses
# to "other" so a future/unexpected schema field can never smuggle free-form
# model output into the cost ledger.
ALLOWED_DECISION_LABELS = {
    "approve_trade",
    "wait",
    "reject",
    "no_trade",
    "reduce_size",
    "close_position",
    "skip",
    "watch",
    "analyze",
    "priority_analyze",
    "position_management_bypass",
    "hold",
    "increase_size",
}

# Decisions that represent "no concrete trading action taken" -- used to
# derive the was_call_necessary heuristic and the cost-breakdown tool's
# "no-action cost" reporting.
LOW_VALUE_DECISION_LABELS = {"wait", "no_trade", "skip", "reject", "hold"}

# Estimated USD price per 1,000 tokens, by model. These are operator-set
# *estimates* for cost-awareness, not an authoritative provider price list --
# override per model via the LLM_COST_PRICING_JSON env var, e.g.
# '{"gpt-5.5": {"input_per_1k": 0.003, "output_per_1k": 0.012}}'.
DEFAULT_MODEL_PRICING_PER_1K_USD: Dict[str, Dict[str, float]] = {
    "gpt-5.4-nano": {"input_per_1k": 0.00005, "output_per_1k": 0.0002},
    "gpt-5.4-mini": {"input_per_1k": 0.00025, "output_per_1k": 0.001},
    "gpt-5.4": {"input_per_1k": 0.00125, "output_per_1k": 0.005},
    "gpt-5.5": {"input_per_1k": 0.0025, "output_per_1k": 0.01},
    "deepseek-chat": {"input_per_1k": 0.00014, "output_per_1k": 0.00028},
    "claude-opus-4-6": {"input_per_1k": 0.015, "output_per_1k": 0.075},
}

_SECRET_PATTERN = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{10,}|(?i:bearer)\s+[A-Za-z0-9._-]{10,})"
)


def _load_pricing_overrides() -> Dict[str, Dict[str, float]]:
    raw = os.getenv("LLM_COST_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for model, prices in parsed.items():
        if isinstance(prices, dict):
            out[str(model)] = {
                "input_per_1k": float(prices.get("input_per_1k", 0.0) or 0.0),
                "output_per_1k": float(prices.get("output_per_1k", 0.0) or 0.0),
            }
    return out


def _build_pricing_table() -> Dict[str, Dict[str, float]]:
    table = {k: dict(v) for k, v in DEFAULT_MODEL_PRICING_PER_1K_USD.items()}
    table.update(_load_pricing_overrides())
    return table


MODEL_PRICING_PER_1K_USD: Dict[str, Dict[str, float]] = _build_pricing_table()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_scalar(value: Any, *, max_len: int = 64) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    text = _SECRET_PATTERN.sub("[REDACTED]", text)
    return text[:max_len]


def _cfg_bool(cfg: Any, name: str, default: bool = True) -> bool:
    if cfg is None:
        return default
    try:
        return bool(getattr(cfg, name, default))
    except Exception:
        return default


def set_current_cycle_id(cycle_id: Optional[str]) -> None:
    """Set the cycle identifier attached to every cost-ledger row written from
    this thread until changed again. Purely an observability label -- never
    read back by trading logic."""
    _local.cycle_id = cycle_id


def get_current_cycle_id() -> Optional[str]:
    return getattr(_local, "cycle_id", None)


@contextmanager
def cycle_context(cycle_id: str):
    previous = get_current_cycle_id()
    set_current_cycle_id(cycle_id)
    try:
        yield
    finally:
        set_current_cycle_id(previous)


def _safe_decision_label(value: Any) -> Optional[str]:
    if value is None:
        return None
    label = str(value).strip().lower()
    return label if label in ALLOWED_DECISION_LABELS else "other"


def _necessity_label(decision_label: Optional[str], call_outcome: str) -> str:
    if call_outcome != "success":
        return "unknown"
    if decision_label is None:
        return "unknown"
    return "no" if decision_label in LOW_VALUE_DECISION_LABELS else "yes"


def estimate_cost_usd(
    model: str, input_tokens: Optional[int], output_tokens: Optional[int]
) -> Optional[float]:
    pricing = MODEL_PRICING_PER_1K_USD.get(model)
    if not pricing or input_tokens is None or output_tokens is None:
        return None
    cost = (input_tokens / 1000.0) * pricing.get("input_per_1k", 0.0) + (
        output_tokens / 1000.0
    ) * pricing.get("output_per_1k", 0.0)
    return round(cost, 8)


def _append(entry: Dict[str, Any]) -> None:
    line = json.dumps(entry, ensure_ascii=False)
    with _write_lock:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def record_llm_call(
    *,
    provider: str,
    model: str,
    ticker: str,
    stage: str,
    attempt: int = 1,
    agent: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    latency_ms: Optional[float] = None,
    call_outcome: str = "success",
    error_type: Optional[str] = None,
    decision_result: Optional[str] = None,
    cache_hit: bool = False,
    skipped_due_budget: bool = False,
    cfg: Any = None,
) -> None:
    """Append one redacted metadata row for a single LLM call attempt.

    Never raises -- a logging failure must never affect trading control
    flow. Never receives or stores prompt/completion text, only scalars.
    """
    if not _cfg_bool(cfg, "llm_cost_ledger_enabled", True):
        return
    try:
        total_tokens: Optional[int] = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = int(input_tokens or 0) + int(output_tokens or 0)

        decision_label = _safe_decision_label(decision_result)

        entry = {
            "timestamp": _now_iso(),
            "cycle_id": _redact_scalar(get_current_cycle_id(), max_len=128),
            "ticker": _redact_scalar(ticker, max_len=32),
            "agent": _redact_scalar(agent or STAGE_TO_AGENT.get(stage, stage), max_len=64),
            "stage": _redact_scalar(stage, max_len=64),
            "provider": _redact_scalar(provider, max_len=32),
            "model": _redact_scalar(model, max_len=64),
            "attempt": int(attempt),
            "input_tokens": int(input_tokens) if input_tokens is not None else None,
            "output_tokens": int(output_tokens) if output_tokens is not None else None,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimate_cost_usd(model, input_tokens, output_tokens),
            "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
            "call_outcome": _redact_scalar(call_outcome, max_len=32),
            "error_type": _redact_scalar(error_type, max_len=64) if error_type else None,
            "decision_result": decision_label,
            "was_call_necessary": _necessity_label(decision_label, call_outcome),
            "cache_hit": bool(cache_hit),
            "skipped_due_budget": bool(skipped_due_budget),
        }
        _append(entry)
    except Exception:
        # Cost-ledger logging is best-effort observability; it must never
        # break or delay a live LLM call.
        pass
