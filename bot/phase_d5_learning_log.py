from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional


D5_LEARNING_LOG_PHASE = "D5_structured_learning_log_foundation_v1"
D5_LEARNING_LOG_SCHEMA_VERSION = "1.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_lifecycle(value: Any) -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "open": "OPEN",
        "submitted": "OPEN",
        "open_keep_open": "OPEN",
        "partial": "PARTIAL",
        "partially_filled": "PARTIAL",
        "fill_evidence": "PARTIAL",
        "filled": "FILLED",
        "cancelled": "CANCELLED",
        "canceled": "CANCELLED",
        "expired": "EXPIRED",
        "rejected": "REJECTED",
        "terminal_evidence": "CANCELLED",
    }
    return aliases.get(status, "UNKNOWN")


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else ([] if value in (None, "") else [value])


def _active_order(report: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("active_order_summary", "active_order", "order", "lifecycle_event"):
        value = report.get(key)
        if isinstance(value, dict):
            return value
    return {}


def build_phase_d5_learning_event(
    *,
    event_type: str,
    lifecycle_event: Optional[Dict[str, Any]] = None,
    d5_metrics_report: Optional[Dict[str, Any]] = None,
    d45_report: Optional[Dict[str, Any]] = None,
    historical_report: Optional[Dict[str, Any]] = None,
    d4_decision_report: Optional[Dict[str, Any]] = None,
    operator_decision: str = "",
    final_outcome: str = "",
    source: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    event = dict(lifecycle_event or {})
    d5 = dict(d5_metrics_report or {})
    d45 = dict(d45_report or {})
    historical = dict(historical_report or {})
    d4 = dict(d4_decision_report or {})
    active = {
        **_active_order(historical),
        **_active_order(d45),
        **event,
    }
    d5_d4 = d5.get("d4_decision") if isinstance(d5.get("d4_decision"), dict) else {}
    d4_source = {**dict(d5_d4 or {}), **d4}
    blockers = []
    for report in (event, d5, d45, historical, d4):
        blockers.extend(_list(report.get("blockers") if isinstance(report, dict) else []))

    d45_branch = str(d45.get("lifecycle_branch") or "").strip()
    if d45_branch == "blocked_p0_safety_drift":
        lifecycle_branch = "UNKNOWN"
    else:
        lifecycle_branch = _normalize_lifecycle(
            event.get("lifecycle_branch")
        or event.get("lifecycle_status")
        or event.get("normalized_status")
        or event.get("status")
        or d45.get("lifecycle_branch")
        or d5.get("lifecycle_status")
        or (historical.get("current_route") or {}).get("branch")
        )
    reprice_decision = _first_text(
        d4_source.get("reprice_decision"),
        d4_source.get("decision"),
        d4_source.get("selected_option"),
        d4_source.get("proposed_action"),
        d45.get("recommended_operator_action"),
    )

    learning_event = {
        "schema_version": D5_LEARNING_LOG_SCHEMA_VERSION,
        "generated_at": (now or _now()).isoformat(),
        "event_type": str(event_type or "execution_observation"),
        "ticker": _first_text(active.get("ticker"), active.get("product_id"), event.get("ticker")),
        "client_order_id": _first_text(active.get("client_order_id"), event.get("client_order_id")),
        "exchange_order_id": _first_text(
            active.get("exchange_order_id"),
            active.get("order_id"),
            event.get("exchange_order_id"),
        ),
        "linked_position_id": _first_text(active.get("linked_position_id"), event.get("linked_position_id")),
        "phase": D5_LEARNING_LOG_PHASE,
        "source": _first_text(source, d5.get("phase"), d45.get("phase"), historical.get("phase"), event.get("phase")),
        "lifecycle_branch": lifecycle_branch,
        "planned_entry_price": _first_text(d5.get("planned_entry_price"), event.get("planned_entry_price")),
        "planned_exit_price": _first_text(
            d5.get("planned_exit_price"),
            event.get("planned_exit_price"),
            active.get("limit_price"),
        ),
        "actual_fill_price": _first_text(d5.get("realized_exit_price"), d5.get("avg_fill_price"), event.get("avg_fill_price")),
        "current_market_mid": _first_text(
            event.get("current_market_mid"),
            event.get("market_mid"),
            (d45.get("trigger_evaluation") or {}).get("market", {}).get("market_mid")
            if isinstance(d45.get("trigger_evaluation"), dict)
            else "",
        ),
        "target_distance_abs": _first_text(
            d5.get("target_distance_abs"),
            (d45.get("trigger_evaluation") or {}).get("market", {}).get("distance_abs")
            if isinstance(d45.get("trigger_evaluation"), dict)
            else "",
            (historical.get("market_distance") or {}).get("distance_abs")
            if isinstance(historical.get("market_distance"), dict)
            else "",
        ),
        "target_distance_pct": _first_text(
            d5.get("target_distance_pct"),
            (d45.get("trigger_evaluation") or {}).get("market", {}).get("distance_pct_of_limit")
            if isinstance(d45.get("trigger_evaluation"), dict)
            else "",
            (historical.get("market_distance") or {}).get("distance_pct_of_limit")
            if isinstance(historical.get("market_distance"), dict)
            else "",
        ),
        "target_distance_band": _first_text(
            d5.get("target_distance_band"),
            (d45.get("trigger_evaluation") or {}).get("market", {}).get("band")
            if isinstance(d45.get("trigger_evaluation"), dict)
            else "",
            (historical.get("market_distance") or {}).get("band")
            if isinstance(historical.get("market_distance"), dict)
            else "",
        ),
        "no_fill_duration_seconds": _first_text(d5.get("no_fill_duration_seconds")),
        "stale_order_age_seconds": _first_text(d5.get("stale_order_age_seconds")),
        "fill_count": int(d5.get("fill_count") or event.get("fill_count") or active.get("fill_count") or 0),
        "filled_base": _first_text(d5.get("filled_base"), event.get("filled_base"), active.get("filled_base"), "0"),
        "filled_quote": _first_text(d5.get("filled_quote"), event.get("filled_quote"), active.get("filled_quote"), "0"),
        "remaining_size": _first_text(event.get("remaining_size"), active.get("remaining_size")),
        "fees": _first_text(d5.get("fee_quote"), event.get("fees"), "0"),
        "slippage_vs_decision_mid_pct": _first_text(d5.get("slippage_vs_decision_mid_pct")),
        "slippage_vs_best_bid_or_ask_pct": _first_text(d5.get("slippage_vs_best_bid_or_ask_pct")),
        "reprice_decision": reprice_decision,
        "reprice_reason": _first_text(d4_source.get("reason"), d4_source.get("recommendation_reason")),
        "cancel_replace_outcome": _first_text(d4_source.get("cancel_replace_outcome"), d5.get("cancel_replace_outcome")),
        "operator_decision": _first_text(operator_decision, d45.get("recommended_operator_action")),
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item or "").strip())),
        "safety_drift": bool(blockers)
        or str(d45.get("lifecycle_branch") or "").strip() == "blocked_p0_safety_drift"
        or str((historical.get("local_state") or {}).get("status") or "") == "blocked_p0_review_required",
        "final_outcome": _first_text(final_outcome, d5.get("fill_quality_label"), d45.get("next_route")),
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "report_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
    }
    return _json_safe(learning_event)


def build_phase_d5_learning_log_report(
    *,
    events: Iterable[Dict[str, Any]],
    window_start: str = "",
    window_end: str = "",
    source: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    rows = [dict(event) for event in events]
    report = {
        "generated_at": (now or _now()).isoformat(),
        "phase": D5_LEARNING_LOG_PHASE,
        "status": "d5_learning_log_report_ready",
        "schema_version": D5_LEARNING_LOG_SCHEMA_VERSION,
        "window_start": str(window_start or ""),
        "window_end": str(window_end or ""),
        "source": str(source or ""),
        "event_count": len(rows),
        "events": rows,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "report_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
    }
    return _json_safe(report)


def events_to_jsonl(events: Iterable[Dict[str, Any]]) -> str:
    return "\n".join(json.dumps(_json_safe(event), sort_keys=True, ensure_ascii=False) for event in events)


__all__ = [
    "D5_LEARNING_LOG_PHASE",
    "D5_LEARNING_LOG_SCHEMA_VERSION",
    "build_phase_d5_learning_event",
    "build_phase_d5_learning_log_report",
    "events_to_jsonl",
]
