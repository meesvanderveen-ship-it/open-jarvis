from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_c_live_guard import build_phase_c_config_snapshot
from bot.phase_c_live_submitter import build_phase_c_live_entry_payload
from bot.phase_c32_staged_pilot_config import (
    build_phase_c32_staged_config,
    build_phase_c32_staged_pilot_report,
)

ZERO = Decimal("0")
C33_MAX_QUOTE_CAP = Decimal("10.00")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _get_pending_context(candidate: Dict[str, Any]) -> Dict[str, Any]:
    analysis = _as_dict(candidate.get("analysis"))
    direct = analysis.get("paper_pending_order_intent")
    if isinstance(direct, dict):
        return direct
    feature_pack = _as_dict(analysis.get("feature_pack"))
    decision_context = _as_dict(feature_pack.get("decision_context"))
    ctx = decision_context.get("pending_order_intent")
    if isinstance(ctx, dict):
        return ctx
    direct_candidate = candidate.get("pending_order_intent")
    return direct_candidate if isinstance(direct_candidate, dict) else {}


def _get_risk(candidate: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("live_risk_result", "risk", "risk_result"):
        val = candidate.get(key)
        if isinstance(val, dict):
            return val
    return {}


def _extract_candidate_snapshot(candidate: Optional[Dict[str, Any]], *, ticker: str) -> Dict[str, Any]:
    """Normalize a fresh candidate snapshot for C.3.3 reporting.

    This function performs only structural extraction. It does not call Coinbase
    and does not decide to submit. The deterministic C.0 guard remains the source
    of truth for final candidate readiness.
    """
    ticker_n = _normalize_ticker(ticker)
    if not isinstance(candidate, dict):
        return {
            "candidate_snapshot_provided": False,
            "ticker": ticker_n,
            "blockers": ["candidate_snapshot_not_provided"],
            "warnings": [],
        }

    analysis = _as_dict(candidate.get("analysis"))
    execution_plan = _as_dict(candidate.get("execution_plan"))
    order_intent = _as_dict(candidate.get("order_intent") or analysis.get("paper_order"))
    judge = _as_dict(analysis.get("judge") or candidate.get("judge"))
    risk = _get_risk(candidate)
    orderbook = _as_dict(execution_plan.get("orderbook_summary"))
    pending = _get_pending_context(candidate)

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    candidate_ticker = _normalize_ticker(candidate.get("ticker") or analysis.get("ticker") or order_intent.get("ticker") or ticker_n)
    if candidate_ticker and candidate_ticker != ticker_n:
        blockers.append("candidate_ticker_mismatch")
    else:
        passed.append("candidate_ticker_matches_pilot_ticker")

    pending_intent_id = str(pending.get("intent_id") or pending.get("id") or order_intent.get("intent_id") or order_intent.get("linked_trade_plan_id") or "").strip()
    fresh_analysis_id = str(candidate.get("fresh_analysis_id") or analysis.get("analysis_id") or analysis.get("fresh_analysis_id") or "").strip()
    if pending_intent_id:
        passed.append("pending_intent_id_present")
    else:
        blockers.append("pending_intent_id_missing")
    if fresh_analysis_id:
        passed.append("fresh_analysis_id_present")
    else:
        warnings.append("fresh_analysis_id_missing_or_not_logged_in_candidate")

    decision = str(judge.get("decision") or "").strip().lower()
    side = str(order_intent.get("side") or judge.get("side") or "").strip().upper()
    if decision == "approve_trade" and side == "BUY":
        passed.append("judge_buy_approval_present")
    else:
        blockers.append("judge_buy_approval_missing")

    quote = _to_decimal(order_intent.get("size_quote") or judge.get("size_quote") or judge.get("quote_size"), "0")
    limit_price = _to_decimal(order_intent.get("limit_price"), "0")
    if quote > ZERO and quote <= C33_MAX_QUOTE_CAP:
        passed.append("quote_size_within_10_usdc_cap")
    elif quote <= ZERO:
        blockers.append("quote_size_missing_or_zero")
    else:
        blockers.append("quote_size_above_10_usdc_cap")
    if limit_price > ZERO:
        passed.append("limit_price_present")
    else:
        blockers.append("limit_price_missing_or_zero")

    action = str(execution_plan.get("execution_action") or order_intent.get("execution_action") or "").strip().lower()
    if action == "place_limit_buy":
        passed.append("execution_action_place_limit_buy")
    else:
        blockers.append("execution_action_not_place_limit_buy")

    if bool(execution_plan.get("read_only")):
        passed.append("execution_plan_read_only")
    else:
        warnings.append("execution_plan_not_marked_read_only")

    if bool(orderbook.get("snapshot_available")) and str(orderbook.get("freshness_status") or "").strip().lower() == "fresh":
        passed.append("orderbook_snapshot_fresh")
    else:
        blockers.append("orderbook_snapshot_not_fresh_or_missing")

    if bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved")):
        mode = str(risk.get("mode") or "").strip().lower()
        if "paper" in mode:
            blockers.append("risk_result_is_paper_not_live")
        else:
            passed.append("live_risk_approval_present")
    else:
        blockers.append("live_risk_approval_missing")

    status = str(pending.get("status") or "").strip().lower()
    if (_truthy(pending.get("trigger_ready")) or status in {"needs_fresh_analysis", "trigger_ready"}) and _truthy(pending.get("requires_fresh_judge_and_risk")):
        passed.append("pending_context_requires_fresh_judge_and_risk")
    else:
        blockers.append("pending_context_not_promotion_ready")

    expiry_minutes = int(_to_decimal(order_intent.get("expiry_minutes") or execution_plan.get("expiry_minutes"), "60"))
    if 5 <= expiry_minutes <= 360:
        passed.append("expiry_minutes_within_safe_bounds")
    else:
        blockers.append("expiry_minutes_outside_safe_bounds")

    return _json_safe({
        "candidate_snapshot_provided": True,
        "ticker": ticker_n,
        "candidate_ticker": candidate_ticker,
        "candidate_snapshot_ready_for_guard": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "pending_intent_id": pending_intent_id,
        "fresh_analysis_id": fresh_analysis_id,
        "judge_snapshot": {
            "decision": decision,
            "side": str(judge.get("side") or side),
            "confidence": judge.get("confidence"),
            "size_quote": str(quote) if quote > ZERO else None,
        },
        "risk_snapshot": {
            "accepted": bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved")),
            "mode": risk.get("mode"),
            "reason": risk.get("reason") or risk.get("message"),
        },
        "orderbook_snapshot": {
            "snapshot_available": bool(orderbook.get("snapshot_available")),
            "freshness_status": orderbook.get("freshness_status"),
            "spread_pct": orderbook.get("spread_pct"),
            "best_bid": orderbook.get("best_bid"),
            "best_ask": orderbook.get("best_ask"),
        },
        "order_intent_snapshot": {
            "side": side,
            "execution_action": action,
            "size_quote": str(quote) if quote > ZERO else None,
            "limit_price": str(limit_price) if limit_price > ZERO else None,
            "expiry_minutes": expiry_minutes,
            "post_only": True,
        },
    })


def build_phase_c33_final_preflight_report(
    *,
    cfg: Any,
    ticker: str,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    max_quote: Any = "10.00",
) -> Dict[str, Any]:
    """Build C.3.3 candidate-capture/final-preflight bridge report.

    C.3.3 deliberately remains read-only. It creates a complete final-preflight
    snapshot and payload preview for a candidate that has already passed the
    staged C.3.2 config path. It never modifies .env, never calls Coinbase and
    never enables ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT.
    """
    ticker_n = _normalize_ticker(ticker)
    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else {}
    candidate_snapshot = _extract_candidate_snapshot(candidate, ticker=ticker_n)
    staged_cfg = build_phase_c32_staged_config(cfg, ticker=ticker_n, max_quote=max_quote)
    c32_report = build_phase_c32_staged_pilot_report(
        cfg=cfg,
        ticker=ticker_n,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        candidate=candidate,
        max_quote=max_quote,
    )

    staged_assessment = c32_report.get("staged_preflight_assessment") or {}
    c30_under_staged = staged_assessment.get("c30_report_under_staged_config") or {}
    c31_under_staged = staged_assessment.get("c31_report_under_staged_config") or {}
    candidate_guard = c30_under_staged.get("candidate_guard_assessment") or {}
    guard_result = candidate_guard.get("guard_result") if isinstance(candidate_guard.get("guard_result"), dict) else {}

    payload_preview = None
    payload_accepted = False
    payload_blockers: List[str] = []
    if isinstance(candidate, dict) and isinstance(guard_result, dict):
        payload_preview = build_phase_c_live_entry_payload(
            cfg=staged_cfg,
            ticker=ticker_n,
            order_intent=_as_dict(candidate.get("order_intent") or _as_dict(candidate.get("analysis")).get("paper_order")),
            guard_result=guard_result,
            product_rules=_as_dict(candidate.get("product_rules")),
        )
        payload_accepted = bool(payload_preview.get("accepted"))
        payload_blockers = list(payload_preview.get("reject_reasons") or [])
    else:
        payload_blockers.append("payload_preview_not_built_without_candidate_and_guard")

    current_snapshot = build_phase_c_config_snapshot(cfg)
    actual_submit_current = bool(current_snapshot.get("enable_phase_c_actual_coinbase_submit"))
    current_submit_disabled = not actual_submit_current
    audit_clean = int(submit_audit_summary.get("live_submission_attempted_count") or 0) == 0 and int(submit_audit_summary.get("live_order_submitted_count") or 0) == 0

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(ticker_n), "ticker_provided", "ticker_missing")
    require(current_submit_disabled, "actual_coinbase_submit_currently_disabled", "actual_coinbase_submit_already_enabled_forbidden")
    require(audit_clean, "submit_audit_live_attempts_zero", "submit_audit_contains_live_attempts_or_submits")
    require(bool(c32_report.get("staged_config_dry_run_ready")), "c32_staged_config_ready", "c32_staged_config_not_ready")
    require(bool(c32_report.get("staged_config_only_ready")), "c32_config_only_ready", "c32_config_only_not_ready")
    require(bool(c32_report.get("actual_coinbase_submit_still_disabled_under_staged_config")), "staged_actual_submit_disabled", "staged_actual_submit_enabled_forbidden")
    require(bool(candidate_snapshot.get("candidate_snapshot_provided")), "candidate_snapshot_provided", "candidate_snapshot_not_provided")
    require(bool(candidate_snapshot.get("candidate_snapshot_ready_for_guard")), "candidate_snapshot_structurally_ready", "candidate_snapshot_structural_blockers")
    require(bool(candidate_guard.get("candidate_guard_ready")), "candidate_guard_ready", "candidate_guard_not_ready")
    require(bool(c31_under_staged.get("ready_for_human_final_c31_review")), "c31_ready_for_human_review_under_staged_config", "c31_not_ready_for_human_review_under_staged_config")
    require(payload_accepted, "payload_preview_accepted", "payload_preview_not_accepted")
    require(not bool(c32_report.get("live_submission_attempted_by_this_tool")), "no_live_attempt_by_c32", "c32_attempted_live_submit_forbidden")
    require(not bool(c32_report.get("live_order_submitted")), "no_live_order_by_c32", "c32_submitted_live_order_forbidden")

    if candidate_snapshot.get("blockers"):
        warnings.append("candidate_snapshot_has_structural_blockers: " + ",".join(candidate_snapshot.get("blockers") or []))
    if payload_blockers:
        warnings.append("payload_preview_reject_reasons: " + ",".join(payload_blockers))

    expiry_minutes = int(_to_decimal((_as_dict(candidate or {}).get("order_intent") or {}).get("expiry_minutes"), "60")) if isinstance(candidate, dict) else 60
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=max(1, expiry_minutes))).isoformat()

    final_snapshot_ready = not blockers
    status = "final_preflight_snapshot_ready_no_submit" if final_snapshot_ready else "blocked"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.3_candidate_capture_final_preflight_bridge",
        "status": status,
        "ticker": ticker_n,
        "final_preflight_snapshot_ready": final_snapshot_ready,
        "ready_for_human_final_pilot_run_review": final_snapshot_ready,
        "actual_coinbase_submit_currently_enabled": actual_submit_current,
        "actual_coinbase_submit_must_remain_false_in_c33": True,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "candidate_snapshot": candidate_snapshot,
        "guard_summary": {
            "candidate_guard_ready": bool(candidate_guard.get("candidate_guard_ready")),
            "guard_allows_live_submit": bool(guard_result.get("guard_allows_live_submit")),
            "hard_block_reasons": list(guard_result.get("hard_block_reasons") or []),
            "passed_checks": list(guard_result.get("passed_checks") or []),
        },
        "payload_preview": payload_preview,
        "final_preflight_snapshot": {
            "ticker": ticker_n,
            "pending_intent_id": candidate_snapshot.get("pending_intent_id"),
            "fresh_analysis_id": candidate_snapshot.get("fresh_analysis_id"),
            "judge_snapshot": candidate_snapshot.get("judge_snapshot"),
            "risk_snapshot": candidate_snapshot.get("risk_snapshot"),
            "orderbook_snapshot": candidate_snapshot.get("orderbook_snapshot"),
            "order_intent_snapshot": candidate_snapshot.get("order_intent_snapshot"),
            "client_order_id_preview": (payload_preview or {}).get("client_order_id"),
            "coinbase_payload_preview": (payload_preview or {}).get("coinbase_payload_preview"),
            "expires_at_preview": expires_at,
            "post_only": bool((payload_preview or {}).get("post_only", True)),
            "max_quote_cap": str(C33_MAX_QUOTE_CAP),
        },
        "c32_report_summary": {
            "status": c32_report.get("status"),
            "staged_config_dry_run_ready": c32_report.get("staged_config_dry_run_ready"),
            "staged_config_only_ready": c32_report.get("staged_config_only_ready"),
            "actual_submit_disabled_under_staged_config": c32_report.get("actual_coinbase_submit_still_disabled_under_staged_config"),
            "ready_for_human_final_c31_review_under_staged_config": c32_report.get("ready_for_human_final_c31_review_under_staged_config"),
        },
        "c31_report_under_staged_config_summary": {
            "status": c31_under_staged.get("status"),
            "ready_for_human_final_c31_review": c31_under_staged.get("ready_for_human_final_c31_review"),
            "final_go_no_go_locked_until_human_enables_actual_submit": c31_under_staged.get("final_go_no_go_locked_until_human_enables_actual_submit"),
            "blockers": c31_under_staged.get("blockers"),
        },
        "required_next_step_before_any_real_order": "C.3.4 final pilot-run procedure with explicit human go/no-go; C.3.3 itself may not submit.",
        "monitoring_commands": [
            "python3 tools/show_phase_c33_candidate_preflight.py --ticker {ticker} --candidate-json /path/to/fresh_candidate.json --json".format(ticker=ticker_n),
            "python3 tools/show_phase_c_submit_readiness.py --json",
            "journalctl -u coinbase-bot -f",
            "tail -f logs/phase_c_live_submit.jsonl logs/order_events.jsonl logs/errors.jsonl",
        ],
        "rollback_env_lines": [
            "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
            "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=false",
            "ENABLE_LIVE_LIMIT_ORDERS=false",
            "ENABLE_LIVE_ENTRY_ORDERS=false",
            "ENABLE_LIVE_EXIT_ORDERS=false",
            "PHASE_C_ALLOWED_TICKERS=",
        ],
        "safety_policy": {
            "c33_is_read_only": True,
            "does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_submit": True,
            "actual_submit_must_remain_false": True,
            "pending_intent_context_only_not_permission": True,
            "fresh_judge_risk_orderbook_required": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "build_phase_c33_final_preflight_report",
]
