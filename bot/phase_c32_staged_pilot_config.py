from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from bot.phase_c_live_guard import build_phase_c_config_snapshot
from bot.phase_c_pilot_readiness import build_phase_c_pilot_readiness_report, summarize_phase_c_submit_audit
from bot.phase_c31_go_no_go import build_phase_c31_go_no_go_report, build_phase_c31_env_preview

ZERO = Decimal("0")
C32_MAX_QUOTE_CAP = Decimal("10.00")


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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


def _object_from_snapshot(snapshot: Dict[str, Any]) -> SimpleNamespace:
    data = dict(snapshot)
    if "phase_c_max_order_quote" in data:
        data["phase_c_max_order_quote"] = _to_decimal(data.get("phase_c_max_order_quote"), "0")
    return SimpleNamespace(**data)


def build_phase_c32_staged_config(cfg: Any, *, ticker: str, max_quote: Any = None) -> Any:
    """Return an in-memory staged C.3.2 config object.

    This intentionally does not mutate cfg or .env. It stages all preflight flags
    needed to make C.3.0/C.3.1 config checks green while keeping actual Coinbase
    submit disabled. Runtime/candidate checks are still evaluated separately.
    """
    ticker_n = _normalize_ticker(ticker)
    base = build_phase_c_config_snapshot(cfg)
    staged = deepcopy(base)
    staged.update({
        "enable_phase_c_live_small_limit_orders": True,
        "enable_live_limit_orders": True,
        "enable_live_entry_orders": True,
        "enable_live_exit_orders": False,
        "enable_phase_c_live_submit_infrastructure": True,
        "enable_phase_c_actual_coinbase_submit": False,
        "phase_c_allowed_tickers": [ticker_n] if ticker_n else [],
        "phase_c_max_order_quote": str(_to_decimal(max_quote if max_quote is not None else staged.get("phase_c_max_order_quote"), "10.00")),
        "phase_c_max_open_entry_orders": 1,
        "phase_c_max_new_orders_per_cycle": 1,
        "phase_c_max_cancels_per_cycle": 1,
        "phase_c_max_replaces_per_cycle": 0,
        "phase_c_require_pending_intent": True,
        "phase_c_require_promotion_ready": True,
        "phase_c_require_fresh_judge": True,
        "phase_c_require_risk_approval": True,
        "phase_c_require_orderbook_freshness": True,
        "phase_c_disable_exit_limit_orders": True,
        "phase_c_live_order_post_only": True,
        "phase_c_entry_order_min_expiry_minutes": max(15, int(staged.get("phase_c_entry_order_min_expiry_minutes") or 15)),
        "phase_c_entry_order_default_expiry_minutes": int(staged.get("phase_c_entry_order_default_expiry_minutes") or 60),
        "phase_c_entry_order_max_expiry_hours": min(6, max(1, int(staged.get("phase_c_entry_order_max_expiry_hours") or 6))),
    })
    # Keep default expiry inside min/max if the current config was odd.
    min_expiry = int(staged["phase_c_entry_order_min_expiry_minutes"])
    max_minutes = int(staged["phase_c_entry_order_max_expiry_hours"]) * 60
    staged["phase_c_entry_order_default_expiry_minutes"] = min(max(int(staged["phase_c_entry_order_default_expiry_minutes"]), min_expiry), max_minutes)
    return _object_from_snapshot(staged)


def assess_phase_c32_current_safety(cfg: Any, *, submit_audit_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Assess whether the currently loaded environment is still safe before staging."""
    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else {}
    snapshot = build_phase_c_config_snapshot(cfg)
    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(str(snapshot.get("execution_mode") or "").lower() == "live", "execution_mode_live", "execution_mode_not_live")
    require(_as_bool(snapshot.get("enable_phase_c_live_submit_infrastructure")), "submit_infrastructure_enabled", "submit_infrastructure_disabled")
    require(not _as_bool(snapshot.get("enable_phase_c_actual_coinbase_submit")), "actual_coinbase_submit_disabled", "actual_coinbase_submit_enabled_danger")
    require(not _as_bool(snapshot.get("enable_live_exit_orders")), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(_as_bool(snapshot.get("phase_c_disable_exit_limit_orders")), "phase_c_disable_exit_limit_orders_true", "phase_c_disable_exit_limit_orders_false")

    if int(submit_audit_summary.get("live_submission_attempted_count") or 0) == 0:
        passed.append("submit_audit_live_attempts_zero")
    else:
        blockers.append("submit_audit_contains_live_attempts")
    if int(submit_audit_summary.get("live_order_submitted_count") or 0) == 0:
        passed.append("submit_audit_live_submits_zero")
    else:
        blockers.append("submit_audit_contains_live_submits")

    if _as_bool(snapshot.get("enable_live_limit_orders")) or _as_bool(snapshot.get("enable_live_entry_orders")):
        if not _as_bool(snapshot.get("enable_phase_c_live_small_limit_orders")):
            blockers.append("live_limit_or_entry_enabled_without_phase_c_master_switch")
        else:
            warnings.append("current_env_already_has_live_entry_preflight_flags_enabled; verify this is intentional")
    else:
        passed.append("current_env_live_entry_flags_still_disabled")

    return _json_safe({
        "generated_at": _now_iso(),
        "current_env_safe_for_c32_staging": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "current_config": snapshot,
        "submit_audit": {
            "sample_size": submit_audit_summary.get("sample_size", 0),
            "live_submission_attempted_count": submit_audit_summary.get("live_submission_attempted_count", 0),
            "live_order_submitted_count": submit_audit_summary.get("live_order_submitted_count", 0),
        },
    })


def assess_phase_c32_staged_preflight(
    *,
    cfg: Any,
    ticker: str,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    max_quote: Any = None,
) -> Dict[str, Any]:
    """Evaluate the staged one-ticker preflight config without applying it."""
    ticker_n = _normalize_ticker(ticker)
    staged_cfg = build_phase_c32_staged_config(cfg, ticker=ticker_n, max_quote=max_quote)
    staged_snapshot = build_phase_c_config_snapshot(staged_cfg)
    c30_report = build_phase_c_pilot_readiness_report(
        cfg=staged_cfg,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        pilot_ticker=ticker_n,
        candidate=candidate,
    )
    c31_report = build_phase_c31_go_no_go_report(
        cfg=staged_cfg,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        ticker=ticker_n,
        candidate=candidate,
    )

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(ticker_n), "ticker_provided", "ticker_missing")
    require(bool(c30_report.get("pilot_config_ready")), "staged_c30_pilot_config_ready", "staged_c30_pilot_config_not_ready")
    require(bool(c30_report.get("submit_infrastructure_ready")), "staged_submit_infrastructure_ready", "staged_submit_infrastructure_not_ready")
    require(bool(c30_report.get("actual_coinbase_submit_still_disabled")), "staged_actual_submit_still_disabled", "staged_actual_submit_enabled_forbidden")
    require(not bool(c31_report.get("actual_coinbase_submit_currently_enabled")), "c31_actual_submit_currently_disabled", "c31_actual_submit_currently_enabled_forbidden")
    require(not bool(c31_report.get("live_submission_attempted_by_this_tool")), "c31_tool_made_no_live_attempt", "c31_tool_attempted_live_submit_forbidden")
    require(not bool(c31_report.get("live_order_submitted")), "c31_tool_submitted_no_live_order", "c31_tool_submitted_live_order_forbidden")

    max_quote_d = _to_decimal(staged_snapshot.get("phase_c_max_order_quote"), "0")
    if max_quote_d > ZERO and max_quote_d <= C32_MAX_QUOTE_CAP:
        passed.append("staged_max_quote_within_10_usdc_cap")
    else:
        blockers.append("staged_max_quote_invalid_or_above_10_usdc_cap")

    if bool(c30_report.get("runtime_candidate_ready")):
        passed.append("runtime_candidate_ready_under_staged_config")
    else:
        warnings.append("runtime_candidate_not_ready_yet; wait_for_promotion_ready_or_fresh_candidate")
    if bool(c30_report.get("candidate_guard_ready")):
        passed.append("candidate_guard_ready_under_staged_config")
    else:
        warnings.append("candidate_guard_not_ready_yet; fresh_judge_risk_orderbook_snapshot_required_before_submit")

    staged_config_dry_run_ready = not blockers
    ready_for_human_review = bool(c31_report.get("ready_for_human_final_c31_review"))

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.2_staged_pilot_config_dry_run_assessment",
        "ticker": ticker_n,
        "staged_config_dry_run_ready": staged_config_dry_run_ready,
        "staged_config_only_ready": bool(c30_report.get("pilot_config_ready")) and bool(c30_report.get("actual_coinbase_submit_still_disabled")),
        "ready_for_human_final_c31_review_under_staged_config": ready_for_human_review,
        "actual_coinbase_submit_still_disabled_under_staged_config": bool(c30_report.get("actual_coinbase_submit_still_disabled")),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "staged_config_snapshot": staged_snapshot,
        "c30_report_under_staged_config": c30_report,
        "c31_report_under_staged_config": c31_report,
        "safety_policy": {
            "staged_only_does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_create_orders": True,
            "actual_submit_forced_false_in_staged_config": True,
            "live_exits_forced_false": True,
            "pending_intent_context_only_not_permission": True,
        },
    })


def build_phase_c32_env_dry_run_commands(*, ticker: str, max_quote: Any = "10.00") -> Dict[str, Any]:
    """Return safe commands for a later manual staged-preflight window.

    The commands intentionally keep ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false.
    They are documentation/preview only; this function does not execute them.
    """
    ticker_n = _normalize_ticker(ticker)
    max_quote_d = _to_decimal(max_quote, "10.00")
    preview = build_phase_c31_env_preview(ticker=ticker_n, max_quote=max_quote_d)
    return _json_safe({
        "ticker": ticker_n,
        "do_not_apply_automatically": True,
        "staged_env_lines": preview.get("staged_preflight_env", []),
        "actual_submit_must_remain_false": True,
        "verification_commands_after_manual_staging": [
            "python3 tools/check_phase_b_imports.py",
            f"python3 tools/show_phase_c32_staged_pilot_config.py --ticker {ticker_n or '<TICKER>'}",
            f"python3 tools/show_phase_c_pilot_readiness.py --ticker {ticker_n or '<TICKER>'}",
            f"python3 tools/show_phase_c31_go_no_go.py --ticker {ticker_n or '<TICKER>'}",
            "python3 tools/show_phase_c_submit_readiness.py",
        ],
        "rollback_env_lines": preview.get("rollback_env", []),
    })


def build_phase_c32_staged_pilot_report(
    *,
    cfg: Any,
    ticker: str,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    max_quote: Any = None,
) -> Dict[str, Any]:
    """Build the complete C.3.2 staged-config dry-run report."""
    ticker_n = _normalize_ticker(ticker)
    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else {}
    current = assess_phase_c32_current_safety(cfg, submit_audit_summary=submit_audit_summary)
    staged = assess_phase_c32_staged_preflight(
        cfg=cfg,
        ticker=ticker_n,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        candidate=candidate,
        max_quote=max_quote,
    )
    blockers: List[str] = []
    blockers.extend([f"current:{x}" for x in current.get("blockers", [])])
    blockers.extend([f"staged:{x}" for x in staged.get("blockers", [])])

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.2_staged_pilot_config_dry_run",
        "ticker": ticker_n,
        "status": "staged_config_ready_no_submit" if not blockers else "blocked",
        "current_env_safe_for_c32_staging": bool(current.get("current_env_safe_for_c32_staging")),
        "staged_config_dry_run_ready": bool(staged.get("staged_config_dry_run_ready")),
        "staged_config_only_ready": bool(staged.get("staged_config_only_ready")),
        "ready_for_human_final_c31_review_under_staged_config": bool(staged.get("ready_for_human_final_c31_review_under_staged_config")),
        "actual_coinbase_submit_still_disabled": bool(current.get("current_config", {}).get("enable_phase_c_actual_coinbase_submit") is False),
        "actual_coinbase_submit_still_disabled_under_staged_config": bool(staged.get("actual_coinbase_submit_still_disabled_under_staged_config")),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": blockers,
        "warnings": list(current.get("warnings", [])) + list(staged.get("warnings", [])),
        "current_safety_assessment": current,
        "staged_preflight_assessment": staged,
        "env_dry_run_preview": build_phase_c32_env_dry_run_commands(ticker=ticker_n, max_quote=max_quote or "10.00"),
        "next_step_guidance": {
            "if_staged_config_ready_but_runtime_not_ready": "Wacht op promotion-ready intent en verse judge/risk/orderbook snapshot; geen submit.",
            "if_ready_for_human_final_c31_review_true": "Nog steeds niet automatisch submitten; voer eerst expliciete C.3.3/final pilot-run procedure uit.",
            "actual_submit_line_forbidden_in_c32": "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true hoort niet in C.3.2.",
        },
        "safety_policy": {
            "c32_is_staged_dry_run_only": True,
            "does_not_modify_env": True,
            "does_not_submit": True,
            "actual_coinbase_submit_must_remain_false": True,
            "live_exit_orders_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "build_phase_c32_staged_config",
    "assess_phase_c32_current_safety",
    "assess_phase_c32_staged_preflight",
    "build_phase_c32_env_dry_run_commands",
    "build_phase_c32_staged_pilot_report",
]
