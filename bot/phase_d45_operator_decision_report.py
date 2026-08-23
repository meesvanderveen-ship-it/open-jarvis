from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


D45_OPERATOR_DECISION_PHASE = "D45_operator_decision_report"
D45_REPRICE_FUTURE_ACK = "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT"
ZERO = Decimal("0")


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


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "submitted": "open",
        "open": "open",
        "open/open": "open",
        "partial": "partial",
        "partially_filled": "partial",
        "filled": "filled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
        "unknown": "unknown",
    }
    return aliases.get(status, status or "unknown")


def _lifecycle_branch(event: Dict[str, Any]) -> str:
    status = _normalize_status(event.get("lifecycle_status") or event.get("normalized_status") or event.get("status"))
    filled_base = _to_decimal(event.get("filled_base"), "0")
    fill_count = int(_to_decimal(event.get("fill_count"), "0"))
    if status == "open" and filled_base <= ZERO and fill_count == 0:
        return "open_keep_open"
    if status in {"partial", "filled"} or filled_base > ZERO or fill_count > 0:
        return "fill_evidence"
    if status in {"cancelled", "expired", "rejected"}:
        return "terminal_evidence"
    return "poll_failure"


def _active_order_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticker": str(event.get("ticker") or "BTC-USDC"),
        "client_order_id": str(event.get("client_order_id") or ""),
        "exchange_order_id": str(event.get("exchange_order_id") or event.get("order_id") or ""),
        "size_base": str(event.get("size_base") or event.get("remaining_size") or ""),
        "limit_price": str(event.get("limit_price") or ""),
        "filled_base": str(event.get("filled_base") or "0"),
        "fill_count": int(_to_decimal(event.get("fill_count"), "0")),
    }


def _d4_preview_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": str(report.get("status") or ""),
        "proposed_action": str(report.get("proposed_action") or ""),
        "proposed_replacement_price": str(report.get("proposed_replacement_price") or ""),
        "activation_state": str(report.get("activation_state") or ""),
        "reason": str(report.get("reason") or ""),
        "blockers": list(report.get("blockers") or []),
        "warnings": list(report.get("warnings") or []),
    }


def _d4_planner_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": str(report.get("status") or ""),
        "proposed_action": str(report.get("proposed_action") or ""),
        "replacement_price": str(report.get("replacement_price") or ""),
        "replacement_size_base": str(report.get("replacement_size_base") or ""),
        "cancel_first_required": bool(report.get("cancel_first_required", True)),
        "replace_only_after_confirmed_cancel": bool(report.get("replace_only_after_confirmed_cancel", True)),
        "blockers": list(report.get("blockers") or []),
        "warnings": list(report.get("warnings") or []),
    }


def _d5_metrics_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": str(report.get("status") or ""),
        "lifecycle_status": str(report.get("lifecycle_status") or ""),
        "fill_quality_label": str(report.get("fill_quality_label") or ""),
        "realized_vs_planned_edge_pct": str(report.get("realized_vs_planned_edge_pct") or ""),
        "no_fill_duration_seconds": str(report.get("no_fill_duration_seconds") or ""),
        "learning_to_execution_allowed": bool(report.get("learning_to_execution_allowed", False)),
        "warnings": list(report.get("warnings") or []),
    }


def build_phase_d45_operator_decision_report(
    *,
    lifecycle_event: Dict[str, Any],
    d4_preview_report: Optional[Dict[str, Any]] = None,
    d4_planner_report: Optional[Dict[str, Any]] = None,
    d5_metrics_report: Optional[Dict[str, Any]] = None,
    operator_mode: str = "decision_only",
    coinbase_client: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or _now()
    event = dict(lifecycle_event or {})
    d4_preview = dict(d4_preview_report or {})
    d4_planner = dict(d4_planner_report or {})
    d5_metrics = dict(d5_metrics_report or {})
    warnings = []
    blockers = []

    if coinbase_client is not None:
        warnings.append("coinbase_client_ignored_report_only")
    if not d4_preview:
        warnings.append("d4_preview_missing")
    if not d4_planner:
        warnings.append("d4_planner_missing")
    if not d5_metrics:
        warnings.append("d5_metrics_missing")
    if operator_mode not in {"wait_only", "decision_only", "future_reprice_consideration"}:
        blockers.append("operator_mode_invalid")

    branch = _lifecycle_branch(event)
    preview_blockers = list(d4_preview.get("blockers") or [])
    planner_blockers = list(d4_planner.get("blockers") or [])
    p0_terms = ("duplicate", "oversell", "reserved_base")
    p0_blocked = any(any(term in str(blocker) for term in p0_terms) for blocker in preview_blockers + planner_blockers)
    d4_candidate = str(d4_preview.get("proposed_action") or "") == "preview_reprice_candidate"
    planner_ready = str(d4_planner.get("proposed_action") or "") == "dry_run_cancel_replace_plan_ready"

    required_ack = ""
    if blockers:
        action = "blocked_p0_review_required"
        reason = blockers[0]
    elif p0_blocked:
        action = "blocked_p0_review_required"
        reason = "duplicate_oversell_or_reservation_safety_blocker"
        blockers.append(reason)
    elif branch == "fill_evidence":
        action = "prepare_fill_lifecycle_apply"
        reason = "d3_fill_evidence_available_ack_required"
    elif branch == "terminal_evidence":
        action = "prepare_terminal_closeout"
        reason = "d3_terminal_evidence_available_ack_required"
    elif branch == "poll_failure":
        action = "monitor_trigger_check"
        reason = "lifecycle_status_unknown_or_poll_failure"
    elif d4_candidate and planner_ready and operator_mode != "wait_only":
        action = "consider_reprice_decision"
        reason = "d4_preview_candidate_and_dry_run_plan_ready_future_ack_required"
        required_ack = str(d4_planner.get("required_future_ack") or D45_REPRICE_FUTURE_ACK)
    else:
        action = "wait_for_trigger"
        reason = "open_keep_open_zero_fills_no_d4_action"

    report = {
        "generated_at": now_dt.isoformat(),
        "phase": D45_OPERATOR_DECISION_PHASE,
        "status": "d45_operator_decision_report_ready" if not blockers or action != "blocked_p0_review_required" else "d45_operator_decision_report_blocked",
        "operator_mode": operator_mode,
        "active_order_summary": _active_order_summary(event),
        "lifecycle_branch": branch,
        "d4_preview_summary": _d4_preview_summary(d4_preview),
        "d4_planner_summary": _d4_planner_summary(d4_planner),
        "d5_metrics_summary": _d5_metrics_summary(d5_metrics),
        "recommended_operator_action": action,
        "reason": reason,
        "blockers": blockers,
        "warnings": warnings,
        "required_future_ack": required_ack,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
    }
    return _json_safe(report)


__all__ = [
    "D45_OPERATOR_DECISION_PHASE",
    "build_phase_d45_operator_decision_report",
]
