from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_c_live_guard import build_phase_c_config_snapshot
from bot.phase_c_pilot_readiness import build_phase_c_pilot_readiness_report, summarize_phase_c_submit_audit

ZERO = Decimal("0")
C31_MAX_QUOTE_CAP = Decimal("10.00")


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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _extract_ticker_from_c30_report(c30_report: Dict[str, Any], explicit_ticker: Optional[str]) -> str:
    explicit = _normalize_ticker(explicit_ticker)
    if explicit:
        return explicit
    report_ticker = _normalize_ticker(c30_report.get("pilot_ticker"))
    if report_ticker:
        return report_ticker
    cfg = c30_report.get("config_assessment") if isinstance(c30_report.get("config_assessment"), dict) else {}
    return _normalize_ticker(cfg.get("pilot_ticker"))


def build_phase_c31_env_preview(*, ticker: str, max_quote: Any = "10.00") -> Dict[str, Any]:
    """Return copy/pasteable but non-mutating env previews for a future pilot.

    The final actual-submit line is intentionally separated from the staged preflight
    block, because C.3.1 preparation must not turn it on automatically.
    """
    ticker = _normalize_ticker(ticker)
    max_quote_d = _to_decimal(max_quote, "10.00")
    staged_lines = [
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
        "ENABLE_LIVE_LIMIT_ORDERS=true",
        "ENABLE_LIVE_ENTRY_ORDERS=true",
        "ENABLE_LIVE_EXIT_ORDERS=false",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
        f"PHASE_C_ALLOWED_TICKERS={ticker or '<KIES-ÉÉN-TICKER>'}",
        f"PHASE_C_MAX_ORDER_QUOTE={max_quote_d}",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS=1",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1",
        "PHASE_C_MAX_CANCELS_PER_CYCLE=1",
        "PHASE_C_MAX_REPLACES_PER_CYCLE=0",
        "PHASE_C_REQUIRE_PENDING_INTENT=true",
        "PHASE_C_REQUIRE_PROMOTION_READY=true",
        "PHASE_C_REQUIRE_FRESH_JUDGE=true",
        "PHASE_C_REQUIRE_RISK_APPROVAL=true",
        "PHASE_C_REQUIRE_ORDERBOOK_FRESHNESS=true",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true",
        "PHASE_C_LIVE_ORDER_POST_ONLY=true",
    ]
    final_arm_lines = [
        "# Alleen handmatig toepassen tijdens het expliciete C.3.1 go-moment en direct terugdraaien:",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true",
    ]
    rollback_lines = [
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=false",
        "ENABLE_LIVE_LIMIT_ORDERS=false",
        "ENABLE_LIVE_ENTRY_ORDERS=false",
        "ENABLE_LIVE_EXIT_ORDERS=false",
        "PHASE_C_ALLOWED_TICKERS=",
    ]
    return {
        "ticker": ticker,
        "staged_preflight_env": staged_lines,
        "final_actual_submit_arm_env": final_arm_lines,
        "rollback_env": rollback_lines,
        "safety_note": "C.3.1-prep toont alleen de stappen; deze functie wijzigt geen .env en plaatst geen orders.",
    }


def assess_phase_c31_pre_go_no_go(
    *,
    cfg: Any,
    c30_report: Dict[str, Any],
    ticker: Optional[str] = None,
    require_candidate_guard: bool = True,
) -> Dict[str, Any]:
    """Assess whether the bot is ready for a later human C.3.1 final go/no-go.

    This does not submit. For this preparation stage, actual Coinbase submit must
    still be disabled. A fully green result means: ready to review, not ready to
    auto-submit.
    """
    c30_report = c30_report if isinstance(c30_report, dict) else {}
    cfg_snapshot = build_phase_c_config_snapshot(cfg)
    pilot_ticker = _extract_ticker_from_c30_report(c30_report, ticker)
    allowed = [_normalize_ticker(t) for t in cfg_snapshot.get("phase_c_allowed_tickers") or [] if _normalize_ticker(t)]
    max_quote = _to_decimal(cfg_snapshot.get("phase_c_max_order_quote"), "0")

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(_as_bool(c30_report.get("pilot_config_ready")), "c30_pilot_config_ready", "c30_pilot_config_not_ready")
    require(_as_bool(c30_report.get("submit_infrastructure_ready")), "submit_infrastructure_ready", "submit_infrastructure_not_ready")
    require(_as_bool(c30_report.get("actual_coinbase_submit_still_disabled")), "actual_coinbase_submit_still_disabled", "actual_coinbase_submit_already_enabled")
    require(_as_bool(c30_report.get("runtime_candidate_ready")), "runtime_candidate_ready", "runtime_candidate_not_ready")

    if require_candidate_guard:
        require(_as_bool(c30_report.get("candidate_guard_ready")), "candidate_guard_ready", "candidate_guard_not_ready_or_missing_fresh_snapshot")
    elif not _as_bool(c30_report.get("candidate_guard_ready")):
        warnings.append("candidate_guard_not_required_for_config_only_review_but_required_before_real_submit")

    require(str(cfg_snapshot.get("execution_mode") or "").lower() == "live", "execution_mode_live", "execution_mode_not_live")
    require(_as_bool(cfg_snapshot.get("enable_phase_c_live_small_limit_orders")), "phase_c_master_switch_enabled", "phase_c_master_switch_disabled")
    require(_as_bool(cfg_snapshot.get("enable_live_limit_orders")), "live_limit_orders_enabled", "live_limit_orders_disabled")
    require(_as_bool(cfg_snapshot.get("enable_live_entry_orders")), "live_entry_orders_enabled", "live_entry_orders_disabled")
    require(not _as_bool(cfg_snapshot.get("enable_live_exit_orders")), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(_as_bool(cfg_snapshot.get("phase_c_disable_exit_limit_orders")), "phase_c_disable_exit_limit_orders_true", "phase_c_disable_exit_limit_orders_false")
    require(_as_bool(cfg_snapshot.get("enable_phase_c_live_submit_infrastructure")), "phase_c_submit_infrastructure_enabled", "phase_c_submit_infrastructure_disabled")
    require(not _as_bool(cfg_snapshot.get("enable_phase_c_actual_coinbase_submit")), "actual_submit_disabled_for_pre_go_no_go", "actual_submit_enabled_before_final_human_go")
    require(_as_bool(cfg_snapshot.get("phase_c_live_order_post_only")), "post_only_enabled", "post_only_disabled")

    if len(allowed) == 1:
        passed.append("exactly_one_allowed_ticker")
    elif not allowed:
        blockers.append("allowed_ticker_missing")
    else:
        blockers.append("more_than_one_allowed_ticker")

    if pilot_ticker and pilot_ticker in allowed:
        passed.append("pilot_ticker_matches_allowed_ticker")
    elif not pilot_ticker:
        blockers.append("pilot_ticker_not_resolved")
    else:
        blockers.append("pilot_ticker_does_not_match_allowed_ticker")

    if max_quote > ZERO and max_quote <= C31_MAX_QUOTE_CAP:
        passed.append("max_quote_within_10_usdc_cap")
    elif max_quote <= ZERO:
        blockers.append("max_quote_not_positive")
    else:
        blockers.append("max_quote_above_10_usdc_cap")

    if int(cfg_snapshot.get("phase_c_max_open_entry_orders") or 0) == 1:
        passed.append("max_open_entry_orders_one")
    else:
        blockers.append("max_open_entry_orders_not_one")
    if int(cfg_snapshot.get("phase_c_max_new_orders_per_cycle") or 0) == 1:
        passed.append("max_new_orders_per_cycle_one")
    else:
        blockers.append("max_new_orders_per_cycle_not_one")
    if int(cfg_snapshot.get("phase_c_max_replaces_per_cycle") or 0) == 0:
        passed.append("max_replaces_per_cycle_zero")
    else:
        blockers.append("max_replaces_per_cycle_not_zero")

    for key, ok, bad in [
        ("phase_c_require_pending_intent", "requires_pending_intent", "pending_intent_requirement_disabled"),
        ("phase_c_require_promotion_ready", "requires_promotion_ready", "promotion_ready_requirement_disabled"),
        ("phase_c_require_fresh_judge", "requires_fresh_judge", "fresh_judge_requirement_disabled"),
        ("phase_c_require_risk_approval", "requires_risk_approval", "risk_approval_requirement_disabled"),
        ("phase_c_require_orderbook_freshness", "requires_orderbook_freshness", "orderbook_freshness_requirement_disabled"),
    ]:
        require(_as_bool(cfg_snapshot.get(key)), ok, bad)

    submit_audit = ((c30_report.get("runtime_assessment") or {}).get("submit_audit") or {}) if isinstance(c30_report.get("runtime_assessment"), dict) else {}
    if int(submit_audit.get("live_submission_attempted_count") or 0) == 0:
        passed.append("submit_audit_live_attempts_zero")
    else:
        blockers.append("submit_audit_contains_live_attempts")
    if int(submit_audit.get("live_order_submitted_count") or 0) == 0:
        passed.append("submit_audit_live_submits_zero")
    else:
        blockers.append("submit_audit_contains_live_submits")

    status = "blocked"
    if not blockers:
        status = "ready_for_human_final_c31_review_no_submit_yet"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.1_pre_go_no_go_assessment",
        "status": status,
        "ready_for_human_final_c31_review": not blockers,
        "ready_to_auto_submit": False,
        "pilot_ticker": pilot_ticker,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "config": cfg_snapshot,
        "c30_summary": {
            "pilot_config_ready": bool(c30_report.get("pilot_config_ready")),
            "runtime_candidate_ready": bool(c30_report.get("runtime_candidate_ready")),
            "candidate_guard_ready": bool(c30_report.get("candidate_guard_ready")),
            "actual_coinbase_submit_still_disabled": bool(c30_report.get("actual_coinbase_submit_still_disabled")),
        },
        "safety_policy": {
            "pre_go_no_go_only": True,
            "no_coinbase_submit": True,
            "actual_submit_must_remain_false_until_final_human_go": True,
            "pending_intent_is_context_not_permission": True,
            "fresh_judge_risk_orderbook_required_before_any_submit": True,
            "live_exit_orders_forbidden": True,
            "master_only_no_followers": True,
        },
    })


def build_phase_c31_go_no_go_report(
    *,
    cfg: Any,
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    ticker: Optional[str] = None,
    candidate: Optional[Dict[str, Any]] = None,
    require_candidate_guard: bool = True,
) -> Dict[str, Any]:
    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else summarize_phase_c_submit_audit()
    c30_report = build_phase_c_pilot_readiness_report(
        cfg=cfg,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        pilot_ticker=ticker,
        candidate=candidate,
    )
    pre_go = assess_phase_c31_pre_go_no_go(
        cfg=cfg,
        c30_report=c30_report,
        ticker=ticker,
        require_candidate_guard=require_candidate_guard,
    )
    pilot_ticker = _normalize_ticker(pre_go.get("pilot_ticker")) or _normalize_ticker(ticker)
    env_preview = build_phase_c31_env_preview(ticker=pilot_ticker, max_quote=getattr(cfg, "phase_c_max_order_quote", "10.00"))
    final_go_no_go_locked = bool(pre_go.get("ready_for_human_final_c31_review")) and not bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.1_controlled_one_ticker_live_pilot_go_no_go_preparation",
        "status": pre_go.get("status"),
        "pilot_ticker": pilot_ticker,
        "ready_for_human_final_c31_review": bool(pre_go.get("ready_for_human_final_c31_review")),
        "final_go_no_go_locked_until_human_enables_actual_submit": final_go_no_go_locked,
        "actual_coinbase_submit_currently_enabled": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "live_order_submitted": False,
        "live_submission_attempted_by_this_tool": False,
        "blockers": list(pre_go.get("blockers") or []),
        "warnings": list(pre_go.get("warnings") or []),
        "pre_go_no_go_assessment": pre_go,
        "c30_readiness_report": c30_report,
        "env_preview": env_preview,
        "required_manual_final_go_steps": [
            "Rerun tools/show_phase_c31_go_no_go.py --json immediately before the pilot.",
            "Confirm ready_for_human_final_c31_review=true and blockers=[].",
            "Confirm logs/phase_c_live_submit.jsonl still has live_submission_attempted_count=0 and live_order_submitted_count=0 before arming.",
            "Only then, during the explicit pilot window, set ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true manually.",
            "Submit only one small post-only entry limit order and immediately set ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false again.",
        ],
        "monitoring_commands": [
            "journalctl -u coinbase-bot -f",
            "tail -f logs/phase_c_live_submit.jsonl logs/order_events.jsonl logs/errors.jsonl",
            "python3 tools/show_phase_c_submit_readiness.py --json",
            "python3 tools/show_phase_c31_go_no_go.py --json",
        ],
        "rollback_commands": [
            "python3 - <<'PY'\nfrom pathlib import Path\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    import re\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\np.write_text(s)\nPY",
            "sudo systemctl restart coinbase-bot",
            "python3 tools/show_phase_c31_go_no_go.py --json",
        ],
        "safety_policy": {
            "tool_is_read_only": True,
            "does_not_modify_env": True,
            "does_not_create_orders": True,
            "actual_submit_remains_manual_and_separate": True,
            "live_exits_remain_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "assess_phase_c31_pre_go_no_go",
    "build_phase_c31_env_preview",
    "build_phase_c31_go_no_go_report",
]
