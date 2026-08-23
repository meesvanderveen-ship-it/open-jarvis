"""Opportunity Radar: latest decision-outcome record per ticker.

state/decision_outcomes.json is a rolling buffer (most recent ~2000 cycle
decisions across all tickers). We only look at recent records and collapse
to "latest record per ticker" — this is exactly what the bot itself most
recently decided about each ticker, including the cycles where it chose to
wait.
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.security.safe_paths import resolve_state_file
from dashboard.backend.services.util import read_json_file

_RECENT_WINDOW = 500


def _score(record: dict) -> float | None:
    candidates = []
    judge_conf = (record.get("judge") or {}).get("confidence")
    gate_conf = (record.get("entry_gate") or {}).get("confidence")
    pattern_score = (record.get("chart_patterns") or {}).get("best_pattern_score")
    for value in (judge_conf, gate_conf, pattern_score):
        if isinstance(value, (int, float)):
            candidates.append(value)
    if not candidates:
        return None
    return round(sum(candidates) / len(candidates), 1)


def _reason(record: dict) -> str:
    trade_plan = record.get("trade_plan") or {}
    chart_patterns = record.get("chart_patterns") or {}
    return trade_plan.get("trigger") or chart_patterns.get("summary") or record.get("decision_category") or ""


def _build_opportunity(record: dict) -> dict:
    return {
        "ticker": record.get("ticker"),
        "created_at": record.get("created_at"),
        "current_price": record.get("current_price"),
        "decision": record.get("decision"),
        "decision_category": record.get("decision_category"),
        "judge": record.get("judge"),
        "entry_gate": record.get("entry_gate"),
        "trade_plan": record.get("trade_plan"),
        "chart_patterns": record.get("chart_patterns"),
        "opportunity_score": _score(record),
        "reason": _reason(record),
        "setup_type": (record.get("entry_gate") or {}).get("setup_type")
        or (record.get("trade_plan") or {}).get("setup_type"),
    }


def _compute_opportunities() -> dict:
    path = resolve_state_file("decision_outcomes.json")
    data = read_json_file(path, default={})
    records = data.get("records", []) if isinstance(data, dict) else []
    recent = records[-_RECENT_WINDOW:]

    latest_by_ticker: dict[str, dict] = {}
    for record in recent:
        ticker = record.get("ticker")
        if not ticker:
            continue
        existing = latest_by_ticker.get(ticker)
        if existing is None or (record.get("created_at") or "") >= (existing.get("created_at") or ""):
            latest_by_ticker[ticker] = record

    opportunities = [_build_opportunity(r) for r in latest_by_ticker.values()]
    opportunities.sort(key=lambda o: o.get("created_at") or "", reverse=True)

    decision_counts: dict[str, int] = {}
    for o in opportunities:
        key = o.get("decision") or "unknown"
        decision_counts[key] = decision_counts.get(key, 0) + 1

    return {
        "opportunities": opportunities,
        "summary": {
            "ticker_count": len(opportunities),
            "decision_counts": decision_counts,
            "records_scanned": len(recent),
        },
    }


def get_opportunities() -> dict:
    return cache.get_or_compute("opportunities", _compute_opportunities)
