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
from dashboard.backend.services.ticker_universe import filter_to_allowed_tickers
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


# Base score per entry-gate decision: how seriously the gatekeeper is
# already treating this ticker, before any price-structure or trigger
# evidence is layered on. Order matches bot/strategy_engine.py's own
# gate vocabulary (skip < watch < analyze < priority_analyze).
_GATE_BASE_SCORE = {"skip": 8, "watch": 32, "analyze": 52, "priority_analyze": 74}
_NEAR_LEVEL_PCT = 1.5  # within this %, treat price as "at" a support/resistance level
_CLOSE_LEVEL_PCT = 3.0


def _proximity(record: dict) -> dict:
    """How close this ticker looks to an actual entry action right now.

    Deliberately built only from fields this endpoint already returns every
    cycle for every ticker (entry_gate, judge, chart_patterns.market_structure,
    pending_trade_plan) rather than re-reading state/pending_order_intents.json
    or state/pending_trade_plans.json directly: those carry their own
    entry-zone extraction (sometimes text-regex fallback) that can lag or
    disagree with the live judge/gate synthesis for the same cycle, which
    would make a gauge on this screen tell a different story than the
    reasoning the operator sees elsewhere. This trades a little precision on
    the exact entry-zone distance for a score that can never contradict the
    decision already shown on the same card.

    Returns a 0-100 score, a red/orange/green zone, and the short list of
    concrete conditions that produced it -- the conditions are what actually
    justify the needle position, not decoration.
    """
    entry_gate = record.get("entry_gate") or {}
    judge = record.get("judge") or {}
    pending_plan = record.get("pending_trade_plan") or {}
    market_structure = (record.get("chart_patterns") or {}).get("market_structure") or {}
    decision = str(record.get("decision") or "").lower()
    gate_decision = str(entry_gate.get("decision") or "").lower()

    score = float(_GATE_BASE_SCORE.get(gate_decision, 15))
    conditions: list[str] = []
    gate_confidence = entry_gate.get("confidence")
    conditions.append(
        f"Gate: {gate_decision or 'onbekend'}"
        + (f" (confidence {gate_confidence})" if isinstance(gate_confidence, (int, float)) else "")
    )

    trigger_ready = bool(pending_plan.get("trigger_ready"))
    if trigger_ready:
        score = max(score, 88)
        conditions.append("Trigger staat klaar — wacht op verse judge-bevestiging")
    elif pending_plan.get("status"):
        conditions.append(f"Pending plan: {pending_plan.get('status')}")

    dist_support = market_structure.get("distance_to_support_pct")
    dist_resistance = market_structure.get("distance_to_resistance_pct")
    nearest = min(
        (d for d in (dist_support, dist_resistance) if isinstance(d, (int, float))),
        default=None,
    )
    if nearest is not None:
        if nearest <= _NEAR_LEVEL_PCT:
            score += 12
        elif nearest <= _CLOSE_LEVEL_PCT:
            score += 6
        if isinstance(dist_support, (int, float)):
            conditions.append(f"Afstand tot support: {dist_support:.2f}%")
        if isinstance(dist_resistance, (int, float)):
            conditions.append(f"Afstand tot weerstand: {dist_resistance:.2f}%")

    breakout_status = market_structure.get("breakout_status")
    if breakout_status and breakout_status != "none":
        score += 8
        conditions.append(f"Breakout-status: {breakout_status}")

    range_position = market_structure.get("range_position")
    if range_position and range_position != "unknown":
        conditions.append(f"Structuur: {range_position}")

    # Confidence scales the whole score down when the gate/judge themselves
    # aren't convinced -- a "watch" at 85 confidence should read closer to
    # green than a "watch" at 30, even with identical structure evidence.
    confidences = [v for v in (judge.get("confidence"), gate_confidence) if isinstance(v, (int, float))]
    if confidences:
        avg_confidence = min(sum(confidences) / len(confidences), 100.0)
        score *= 0.7 + 0.3 * (avg_confidence / 100.0)

    if decision in {"reject", "close_position"}:
        score = min(score, 20)
        conditions.insert(0, f"Beslissing: {decision}")

    setup_type = entry_gate.get("setup_type") or (record.get("trade_plan") or {}).get("setup_type")
    if setup_type and setup_type != "unclear":
        conditions.append(f"Setup: {setup_type}")

    score = max(0, min(100, round(score)))
    if score >= 70:
        zone = "green"
    elif score >= 40:
        zone = "orange"
    else:
        zone = "red"

    return {"score": score, "zone": zone, "conditions": conditions[:5]}


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
        "proximity": _proximity(record),
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
    opportunities = filter_to_allowed_tickers(opportunities)
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
