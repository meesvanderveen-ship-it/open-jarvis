from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.phase_c_live_guard import build_phase_c_config_snapshot, evaluate_phase_c_live_entry_readiness

ZERO = Decimal("0")
C30_MAX_RECOMMENDED_QUOTE = Decimal("10.00")


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


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


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


def _tickers_from_items(items: Any) -> List[str]:
    tickers: List[str] = []
    for item in _as_list(items):
        if isinstance(item, dict):
            ticker = _normalize_ticker(item.get("ticker"))
        else:
            ticker = _normalize_ticker(item)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _read_jsonl_tail(path: str | Path, limit: int = 100) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-max(1, int(limit)):]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows


def summarize_phase_c_submit_audit(path: str | Path = "logs/phase_c_live_submit.jsonl", sample: int = 100) -> Dict[str, Any]:
    """Summarize C.2/C.2.1 submit-audit rows without touching Coinbase.

    This is intentionally read-only. Any live_submission_attempted/live_order_submitted
    row is surfaced as a C.3.0 blocker because the one-ticker pilot checklist must
    start from a clean disabled-submit posture.
    """
    rows = _read_jsonl_tail(path, limit=sample)
    by_status = Counter(str(r.get("status") or "unknown") for r in rows)
    hard_blocks = Counter()
    for row in rows:
        for reason in row.get("hard_block_reasons") or []:
            hard_blocks[str(reason)] += 1
    attempted = sum(1 for r in rows if bool(r.get("live_submission_attempted")))
    submitted = sum(1 for r in rows if bool(r.get("live_order_submitted")))
    diagnostic = sum(1 for r in rows if bool(r.get("diagnostic")))
    dry_run = sum(1 for r in rows if bool(r.get("dry_run")))
    return {
        "path": str(path),
        "sample_size": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "hard_block_reasons_sample": dict(sorted(hard_blocks.items())),
        "live_submission_attempted_count": attempted,
        "live_order_submitted_count": submitted,
        "diagnostic_count": diagnostic,
        "dry_run_count": dry_run,
        "latest": rows[-5:],
        "submit_audit_clean_for_c30": attempted == 0 and submitted == 0,
    }


def _open_entry_orders_from_order_summary(order_summary: Dict[str, Any], ticker: str) -> Tuple[int, int]:
    ticker = _normalize_ticker(ticker)
    open_entries_total = 0
    open_entries_for_ticker = 0

    # Preferred path for tools/tests that pass richer order details.
    open_entry_orders = order_summary.get("open_entry_orders")
    if isinstance(open_entry_orders, list):
        for order in open_entry_orders:
            if not isinstance(order, dict):
                continue
            open_entries_total += 1
            if _normalize_ticker(order.get("ticker")) == ticker:
                open_entries_for_ticker += 1
        return open_entries_total, open_entries_for_ticker

    # Backward-compatible fallback: OrderStore.summary() only has counts.
    counts = order_summary.get("open_order_counts") if isinstance(order_summary.get("open_order_counts"), dict) else {}
    if counts:
        for key, value in counts.items():
            key_l = str(key).lower()
            if "entry" in key_l or "buy" in key_l:
                try:
                    open_entries_total += int(value)
                except Exception:
                    pass
    return open_entries_total, open_entries_for_ticker


def assess_phase_c_pilot_config(cfg: Any, *, pilot_ticker: Optional[str] = None) -> Dict[str, Any]:
    """Assess static C.3.0 pilot configuration.

    C.3.0 is not the live submit phase. Therefore ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT
    must still be false for this checklist to be considered safe.
    """
    snapshot = build_phase_c_config_snapshot(cfg)
    allowed = [_normalize_ticker(t) for t in snapshot.get("phase_c_allowed_tickers") or [] if _normalize_ticker(t)]
    requested = _normalize_ticker(pilot_ticker) if pilot_ticker else (allowed[0] if len(allowed) == 1 else "")
    max_quote = _to_decimal(snapshot.get("phase_c_max_order_quote"), "0")

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(str(snapshot.get("execution_mode") or "").lower() == "live", "execution_mode_live", "execution_mode_not_live")
    require(bool(snapshot.get("enable_limit_order_manager")), "limit_order_manager_enabled", "limit_order_manager_disabled")
    require(bool(snapshot.get("enable_phase_c_live_small_limit_orders")), "phase_c_master_switch_enabled", "phase_c_master_switch_disabled")
    require(bool(snapshot.get("enable_live_limit_orders")), "live_limit_orders_enabled", "live_limit_orders_disabled")
    require(bool(snapshot.get("enable_live_entry_orders")), "live_entry_orders_enabled", "live_entry_orders_disabled")
    require(not bool(snapshot.get("enable_live_exit_orders")), "live_exit_orders_disabled", "live_exit_orders_enabled")
    require(bool(snapshot.get("phase_c_disable_exit_limit_orders")), "phase_c_exit_limit_disable_flag_true", "phase_c_exit_limit_disable_flag_false")
    require(bool(snapshot.get("enable_phase_c_live_submit_infrastructure")), "submit_infrastructure_enabled", "submit_infrastructure_disabled")
    require(not bool(snapshot.get("enable_phase_c_actual_coinbase_submit")), "actual_coinbase_submit_still_disabled", "actual_coinbase_submit_enabled_in_c30")
    require(bool(snapshot.get("phase_c_live_order_post_only")), "post_only_enabled", "post_only_disabled")

    if len(allowed) == 1:
        passed.append("exactly_one_phase_c_allowed_ticker")
    elif not allowed:
        blockers.append("phase_c_allowed_tickers_empty")
    else:
        blockers.append("phase_c_allowed_tickers_must_contain_exactly_one_ticker")

    if requested:
        if requested in allowed:
            passed.append("pilot_ticker_is_allowed")
        else:
            blockers.append("pilot_ticker_not_in_phase_c_allowed_tickers")
    else:
        blockers.append("pilot_ticker_not_resolved")

    require(max_quote > ZERO, "phase_c_max_order_quote_positive", "phase_c_max_order_quote_not_positive")
    if max_quote > C30_MAX_RECOMMENDED_QUOTE:
        blockers.append("phase_c_max_order_quote_above_c30_recommended_cap_10_usdc")
    else:
        passed.append("phase_c_max_order_quote_within_c30_cap")

    require(int(snapshot.get("phase_c_max_open_entry_orders") or 0) == 1, "max_open_entry_orders_is_one", "max_open_entry_orders_must_be_one_for_c30")
    require(int(snapshot.get("phase_c_max_new_orders_per_cycle") or 0) == 1, "max_new_orders_per_cycle_is_one", "max_new_orders_per_cycle_must_be_one_for_c30")
    require(int(snapshot.get("phase_c_max_cancels_per_cycle") or 0) <= 1, "max_cancels_per_cycle_not_above_one", "max_cancels_per_cycle_above_one_for_c30")
    require(int(snapshot.get("phase_c_max_replaces_per_cycle") or 0) == 0, "max_replaces_per_cycle_zero", "max_replaces_per_cycle_must_be_zero_for_c30")

    for attr, ok, bad in [
        ("phase_c_require_pending_intent", "requires_pending_intent", "pending_intent_requirement_disabled"),
        ("phase_c_require_promotion_ready", "requires_promotion_ready", "promotion_ready_requirement_disabled"),
        ("phase_c_require_fresh_judge", "requires_fresh_judge", "fresh_judge_requirement_disabled"),
        ("phase_c_require_risk_approval", "requires_risk_approval", "risk_approval_requirement_disabled"),
        ("phase_c_require_orderbook_freshness", "requires_orderbook_freshness", "orderbook_freshness_requirement_disabled"),
    ]:
        require(bool(snapshot.get(attr)), ok, bad)

    min_expiry = int(snapshot.get("phase_c_entry_order_min_expiry_minutes") or 0)
    default_expiry = int(snapshot.get("phase_c_entry_order_default_expiry_minutes") or 0)
    max_expiry_hours = int(snapshot.get("phase_c_entry_order_max_expiry_hours") or 0)
    require(min_expiry >= 5, "entry_min_expiry_not_too_short", "entry_min_expiry_too_short")
    require(default_expiry >= min_expiry, "entry_default_expiry_above_min", "entry_default_expiry_below_min")
    require(max_expiry_hours <= 6, "entry_max_expiry_not_above_6h", "entry_max_expiry_above_6h_for_c30")
    require(default_expiry <= max(1, max_expiry_hours) * 60, "entry_default_expiry_within_max", "entry_default_expiry_above_max")

    if not bool(snapshot.get("enable_phase_c_actual_coinbase_submit")):
        warnings.append("actual_coinbase_submit_disabled_expected_for_c30; future C.3.1 still needs explicit enable")

    return _json_safe({
        "generated_at": _now_iso(),
        "pilot_ticker": requested,
        "allowed_tickers": allowed,
        "pilot_config_ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "config": snapshot,
        "actual_coinbase_submit_still_disabled": not bool(snapshot.get("enable_phase_c_actual_coinbase_submit")),
    })


def assess_phase_c_pilot_runtime(
    *,
    cfg: Any,
    pilot_ticker: str,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pending_summary = pending_summary if isinstance(pending_summary, dict) else {}
    order_summary = order_summary if isinstance(order_summary, dict) else {}
    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else {}
    ticker = _normalize_ticker(pilot_ticker)

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    open_total = int(order_summary.get("open_orders") or order_summary.get("open") or 0)
    diagnostics = int(order_summary.get("diagnostic_order_count") or order_summary.get("diagnostics") or 0)
    open_entry_total, open_entry_for_ticker = _open_entry_orders_from_order_summary(order_summary, ticker)

    if open_total == 0:
        passed.append("no_open_orders")
    else:
        blockers.append("open_orders_present")
    if open_entry_for_ticker == 0:
        passed.append("no_open_entry_order_for_pilot_ticker")
    else:
        blockers.append("open_entry_order_for_pilot_ticker_present")
    if diagnostics == 0:
        passed.append("no_diagnostic_orders_in_order_store")
    else:
        warnings.append("diagnostic_orders_present_in_order_store")

    promotion_tickers = _tickers_from_items(pending_summary.get("promotion_ready") or pending_summary.get("promotion_ready_current"))
    trigger_tickers = _tickers_from_items(pending_summary.get("trigger_ready") or pending_summary.get("trigger_ready_current"))
    fresh_tickers = _tickers_from_items(pending_summary.get("needs_fresh_analysis") or pending_summary.get("needs_fresh_analysis_current"))

    if ticker in promotion_tickers:
        passed.append("pilot_ticker_has_promotion_ready_intent")
    else:
        blockers.append("pilot_ticker_has_no_promotion_ready_intent")
    if ticker in trigger_tickers or ticker in fresh_tickers or ticker in promotion_tickers:
        passed.append("pilot_ticker_has_current_pending_context")
    else:
        blockers.append("pilot_ticker_has_no_current_pending_context")

    if submit_audit_summary.get("submit_audit_clean_for_c30", True):
        passed.append("submit_audit_has_no_live_attempts_or_submits")
    else:
        blockers.append("submit_audit_contains_live_attempts_or_submits")

    if bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)):
        blockers.append("actual_coinbase_submit_enabled_in_c30")
    else:
        passed.append("actual_coinbase_submit_disabled")

    return _json_safe({
        "generated_at": _now_iso(),
        "pilot_ticker": ticker,
        "runtime_candidate_ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "orders": {
            "open_orders": open_total,
            "open_entry_orders_total": open_entry_total,
            "open_entry_orders_for_pilot_ticker": open_entry_for_ticker,
            "diagnostic_order_count": diagnostics,
        },
        "pending_order_intents": {
            "promotion_ready_tickers": promotion_tickers,
            "trigger_ready_tickers": trigger_tickers,
            "needs_fresh_analysis_tickers": fresh_tickers,
            "open_intents": pending_summary.get("open_intents") or pending_summary.get("active_intents"),
            "total_intents": pending_summary.get("total_intents"),
        },
        "submit_audit": {
            "sample_size": submit_audit_summary.get("sample_size", 0),
            "live_submission_attempted_count": submit_audit_summary.get("live_submission_attempted_count", 0),
            "live_order_submitted_count": submit_audit_summary.get("live_order_submitted_count", 0),
            "submit_audit_clean_for_c30": submit_audit_summary.get("submit_audit_clean_for_c30", True),
        },
    })


def assess_phase_c_candidate_guard(
    *,
    cfg: Any,
    pilot_ticker: str,
    candidate: Optional[Dict[str, Any]] = None,
    open_live_entry_orders_count: int = 0,
    new_live_orders_this_cycle: int = 0,
) -> Dict[str, Any]:
    """Optionally run the existing Phase-C guard against a fresh candidate snapshot.

    The candidate is expected to be a JSON dict with analysis, execution_plan,
    order_intent, risk/live_risk_result and optional product_rules. This function
    still does not submit; it only exposes whether fresh judge/risk/orderbook checks
    would pass the existing deterministic guard.
    """
    if not isinstance(candidate, dict):
        return {
            "candidate_guard_evaluated": False,
            "candidate_guard_ready": False,
            "blockers": ["candidate_snapshot_not_provided"],
            "warnings": ["fresh_judge_risk_orderbook_can_only_be_checked_with_candidate_snapshot"],
            "guard_result": None,
        }

    risk = candidate.get("live_risk_result") if isinstance(candidate.get("live_risk_result"), dict) else candidate.get("risk")
    guard = evaluate_phase_c_live_entry_readiness(
        cfg=cfg,
        ticker=pilot_ticker,
        analysis=candidate.get("analysis") if isinstance(candidate.get("analysis"), dict) else {},
        execution_plan=candidate.get("execution_plan") if isinstance(candidate.get("execution_plan"), dict) else {},
        order_intent=candidate.get("order_intent") if isinstance(candidate.get("order_intent"), dict) else None,
        live_risk_result=risk if isinstance(risk, dict) else None,
        open_live_entry_orders_count=open_live_entry_orders_count,
        new_live_orders_this_cycle=new_live_orders_this_cycle,
    )
    return _json_safe({
        "candidate_guard_evaluated": True,
        "candidate_guard_ready": bool(guard.get("guard_allows_live_submit")),
        "blockers": list(guard.get("hard_block_reasons") or []),
        "passed_checks": list(guard.get("passed_checks") or []),
        "guard_result": guard,
        "safety_policy": "Guard evaluation only; no Coinbase submit.",
    })


def build_phase_c_pilot_readiness_report(
    *,
    cfg: Any,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    pilot_ticker: Optional[str] = None,
    candidate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config_assessment = assess_phase_c_pilot_config(cfg, pilot_ticker=pilot_ticker)
    resolved_ticker = _normalize_ticker(config_assessment.get("pilot_ticker"))
    runtime = assess_phase_c_pilot_runtime(
        cfg=cfg,
        pilot_ticker=resolved_ticker,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
    ) if resolved_ticker else {
        "runtime_candidate_ready": False,
        "blockers": ["pilot_ticker_not_resolved"],
    }
    candidate_guard = assess_phase_c_candidate_guard(
        cfg=cfg,
        pilot_ticker=resolved_ticker,
        candidate=candidate,
        open_live_entry_orders_count=int((runtime.get("orders") or {}).get("open_entry_orders_for_pilot_ticker") or 0) if isinstance(runtime, dict) else 0,
        new_live_orders_this_cycle=0,
    )

    submit_infrastructure_ready = bool(getattr(cfg, "enable_phase_c_live_submit_infrastructure", True))
    actual_disabled = not bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    c30_safe = bool(config_assessment.get("pilot_config_ready")) and submit_infrastructure_ready and actual_disabled

    # Runtime candidate readiness is deliberately separate. It may be false when
    # no promotion-ready setup exists, while config/infrastructure can still be
    # correctly prepared for a later C.3.1 decision.
    all_blockers = []
    all_blockers.extend([f"config:{x}" for x in config_assessment.get("blockers", [])])
    all_blockers.extend([f"runtime:{x}" for x in runtime.get("blockers", [])])
    if not submit_infrastructure_ready:
        all_blockers.append("submit_infrastructure_disabled")
    if not actual_disabled:
        all_blockers.append("actual_coinbase_submit_enabled_in_c30")

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.0_controlled_one_ticker_pilot_readiness",
        "pilot_ticker": resolved_ticker,
        "pilot_config_ready": bool(config_assessment.get("pilot_config_ready")),
        "submit_infrastructure_ready": submit_infrastructure_ready,
        "actual_coinbase_submit_still_disabled": actual_disabled,
        "runtime_candidate_ready": bool(runtime.get("runtime_candidate_ready")),
        "candidate_guard_ready": bool(candidate_guard.get("candidate_guard_ready")),
        "c30_safe_to_continue_without_submit": c30_safe,
        "overall_ready_for_future_c31_review": bool(config_assessment.get("pilot_config_ready")) and bool(runtime.get("runtime_candidate_ready")) and actual_disabled,
        "blockers": all_blockers,
        "config_assessment": config_assessment,
        "runtime_assessment": runtime,
        "candidate_guard_assessment": candidate_guard,
        "manual_c31_enable_preview": {
            "do_not_apply_in_c30": True,
            "required_human_steps_later": [
                "Choose exactly one ticker and set PHASE_C_ALLOWED_TICKERS to that ticker.",
                "Keep ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false until the final C.3.1 go/no-go moment.",
                "Verify fresh judge approval, deterministic risk approval and fresh orderbook immediately before any submit.",
                "Enable actual submit only for the controlled pilot window, then roll it back to false.",
            ],
        },
        "rollback_monitoring_checklist": [
            "Before pilot: python3 tools/show_phase_c_pilot_readiness.py --json",
            "Before pilot: python3 tools/show_phase_c_submit_readiness.py --json and confirm live_submission_attempted_count=0/live_order_submitted_count=0",
            "During pilot: journalctl -u coinbase-bot -f and tail -f logs/phase_c_live_submit.jsonl logs/order_events.jsonl logs/errors.jsonl",
            "Rollback: set ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false, ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=false, ENABLE_LIVE_LIMIT_ORDERS=false, ENABLE_LIVE_ENTRY_ORDERS=false, restart service",
            "After rollback: rerun Phase-C readiness and confirm actual_coinbase_submit_still_disabled=true",
        ],
        "safety_policy": {
            "c30_places_no_orders": True,
            "pending_intents_are_context_not_orders": True,
            "fresh_judge_and_deterministic_risk_required": True,
            "actual_coinbase_submit_must_remain_disabled_in_c30": True,
            "live_exit_orders_forbidden_in_phase_c": True,
            "master_only_no_followers_in_order_lifecycle": True,
            "no_unmanaged_gtc_orders": True,
        },
    })


__all__ = [
    "assess_phase_c_pilot_config",
    "assess_phase_c_pilot_runtime",
    "assess_phase_c_candidate_guard",
    "build_phase_c_pilot_readiness_report",
    "summarize_phase_c_submit_audit",
]
