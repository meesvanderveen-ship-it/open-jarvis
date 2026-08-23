"""Multi-Agent Decision Trace for a single ticker.

Builds a step-by-step trace from what is actually persisted to disk per
cycle: the hard-gate/synthesis/judge snapshot in decision_outcomes.json,
any open order/position state, the GrowBot/River learning context embedded
in that same decision record, and the most recent closed-trade reflection
for that ticker (state/trade_reflections.jsonl). Intermediate per-agent LLM
outputs (DeepSeek preprocess, the six analysis archetypes) are not
persisted individually to disk by the bot, so they are not fabricated here.
"""

from __future__ import annotations

from dashboard.backend.security.safe_paths import resolve_state_file
from dashboard.backend.services.orders import get_orders
from dashboard.backend.services.positions import get_positions
from dashboard.backend.services.util import read_json_file

_REFLECTION_TAIL_LINES = 5000


def _latest_decision_record(ticker: str) -> dict | None:
    path = resolve_state_file("decision_outcomes.json")
    data = read_json_file(path, default={})
    records = data.get("records", []) if isinstance(data, dict) else []
    matches = [r for r in records if r.get("ticker") == ticker]
    if not matches:
        return None
    matches.sort(key=lambda r: r.get("created_at") or "")
    return matches[-1]


def _latest_reflection(ticker: str) -> dict | None:
    path = resolve_state_file("trade_reflections.jsonl")
    if not path.is_file():
        return None
    import json as _json

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines[-_REFLECTION_TAIL_LINES:]):
        line = line.strip()
        if not line:
            continue
        try:
            record = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if record.get("ticker") == ticker:
            return record
    return None


def get_ticker_trace(ticker: str) -> dict:
    decision = _latest_decision_record(ticker)
    positions = get_positions()["positions"]
    position = next((p for p in positions if p["ticker"] == ticker), None)
    orders = [o for o in get_orders()["orders"] if (o.get("ticker") or o.get("product_id")) == ticker]
    reflection = _latest_reflection(ticker)

    steps = []

    steps.append(
        {
            "step": "hard_gate",
            "label": "Hard gate",
            "status": "ok" if decision else "no_data",
            "summary": decision.get("entry_gate") if decision else None,
        }
    )
    steps.append(
        {
            "step": "synthesis_trade_plan",
            "label": "Synthesis / trade plan",
            "status": "ok" if decision and decision.get("trade_plan") else "no_data",
            "summary": decision.get("trade_plan") if decision else None,
        }
    )
    steps.append(
        {
            "step": "judge",
            "label": "Final judge",
            "status": "ok" if decision and decision.get("judge") else "no_data",
            "summary": decision.get("judge") if decision else None,
        }
    )
    steps.append(
        {
            "step": "chart_patterns",
            "label": "Chart pattern evidence",
            "status": "ok" if decision and decision.get("chart_patterns") else "no_data",
            "summary": decision.get("chart_patterns") if decision else None,
        }
    )
    steps.append(
        {
            "step": "risk_and_planning",
            "label": "Risk / D2 planner / D3 exit",
            "status": "open_position" if position else "no_open_position",
            "summary": {
                "d2_plan_status": position.get("d2_plan_status"),
                "d3_exit_status": position.get("d3_exit_status"),
                "invalidation_price": position.get("invalidation_price"),
                "position_risk_incomplete": position.get("position_risk_incomplete"),
            }
            if position
            else None,
        }
    )
    steps.append(
        {
            "step": "live_orders",
            "label": "C4.3 entry / D3 exit orders",
            "status": "has_orders" if orders else "no_orders",
            "summary": [
                {
                    "client_order_id": o.get("client_order_id"),
                    "side": o.get("side"),
                    "status": o.get("status"),
                    "phase": o.get("phase"),
                    "is_open": o.get("is_open"),
                }
                for o in orders
            ],
        }
    )
    steps.append(
        {
            "step": "learning_context",
            "label": "GrowBot/River learning context",
            "status": "ok" if decision and decision.get("growbot_river_learning_context") else "no_data",
            "summary": decision.get("growbot_river_learning_context") if decision else None,
        }
    )
    steps.append(
        {
            "step": "reflection",
            "label": "Trade reflection (post-outcome)",
            "status": "ok" if reflection else "no_data",
            "summary": reflection,
        }
    )

    return {
        "ticker": ticker,
        "decision_created_at": decision.get("created_at") if decision else None,
        "decision": decision.get("decision") if decision else None,
        "steps": steps,
        "raw_decision_record": decision,
    }
