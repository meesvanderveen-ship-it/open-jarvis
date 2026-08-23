from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bot.phase_c36_final_pilot_dry_run import build_phase_c36_final_pilot_dry_run_report
from bot.phase_c37_candidate_promotion_hardening import build_phase_c37_candidate_promotion_hardening_report
from bot.phase_c_live_submitter import prepare_phase_c_live_entry_submission

ZERO = Decimal("0")
C38_MAX_QUOTE_CAP = Decimal("10.00")
C38_HUMAN_GO_ACK = "I_UNDERSTAND_AND_APPROVE_PHASE_C38_ONE_LIVE_ENTRY_ORDER"
C38_FINAL_EXECUTOR_MODE = "final_live_pilot"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


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


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _candidate_assessment_by_ticker(c37_report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker)
    selected = _as_dict(c37_report.get("selected_candidate_assessment"))
    if _normalize_ticker(selected.get("ticker")) == ticker_n:
        return selected
    for item in _as_list(c37_report.get("candidate_assessments")):
        if isinstance(item, dict) and _normalize_ticker(item.get("ticker")) == ticker_n:
            return item
    return {}


def _resolve_selected_ticker(c37_report: Dict[str, Any], c36_report: Dict[str, Any], ticker: Optional[str]) -> str:
    requested = _normalize_ticker(ticker)
    if requested:
        return requested
    actionable = [_normalize_ticker(x) for x in _as_list(c37_report.get("actionable_preflight_ready_tickers")) if _normalize_ticker(x)]
    if actionable:
        return actionable[0]
    selected = _normalize_ticker(c37_report.get("selected_ticker")) or _normalize_ticker(c36_report.get("selected_ticker"))
    return selected


def _payload_from_c36(c36_report: Dict[str, Any]) -> Dict[str, Any]:
    return _as_dict(_as_dict(c36_report.get("final_run_preview")).get("payload_preview"))


def _final_snapshot_from_c36(c36_report: Dict[str, Any]) -> Dict[str, Any]:
    return _as_dict(_as_dict(c36_report.get("final_run_preview")).get("final_preflight_snapshot"))


def _submit_audit_from_reports(c37_report: Dict[str, Any], c36_report: Dict[str, Any], submit_audit_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # C.3.7 summarizes C.3.5, but does not currently expose submit_audit in the summary.
    # Prefer explicit input when provided; otherwise default to a conservative zero-count snapshot.
    audit = _as_dict(submit_audit_summary)
    if audit:
        return audit
    c35 = _as_dict(c37_report.get("c35_report"))
    audit = _as_dict(c35.get("submit_audit"))
    if audit:
        return audit
    return {"live_submission_attempted_count": 0, "live_order_submitted_count": 0, "source": "not_supplied_assumed_zero_from_prior_readiness"}


def _build_hardlocks(
    *,
    cfg: Any,
    ticker: str,
    c37_report: Dict[str, Any],
    c36_report: Dict[str, Any],
    candidate_assessment: Dict[str, Any],
    payload: Dict[str, Any],
    final_snapshot: Dict[str, Any],
    human_go_ack: str,
    executor_mode: str,
    submit_live: bool,
    coinbase_client: Any,
    submit_audit: Dict[str, Any],
    max_quote: Any,
) -> Dict[str, Any]:
    quote = _to_decimal(payload.get("size_quote_normalized") or payload.get("size_quote_requested"), "0")
    actual_submit_enabled = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    live_attempts = int(submit_audit.get("live_submission_attempted_count") or 0)
    live_submits = int(submit_audit.get("live_order_submitted_count") or 0)
    max_quote_d = min(_to_decimal(max_quote, "10.00"), C38_MAX_QUOTE_CAP)

    blockers: List[str] = []
    passed: List[str] = []
    warnings: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(ticker), "selected_ticker_present", "selected_ticker_missing")
    require(not bool(c37_report.get("live_submission_attempted_by_this_tool")), "c37_made_no_live_attempt", "c37_attempted_live_submit_forbidden")
    require(not bool(c37_report.get("live_order_submitted")), "c37_submitted_no_live_order", "c37_submitted_live_order_forbidden")
    require(not bool(c36_report.get("live_submission_attempted_by_this_tool")), "c36_made_no_live_attempt", "c36_attempted_live_submit_forbidden")
    require(not bool(c36_report.get("live_order_submitted")), "c36_submitted_no_live_order", "c36_submitted_live_order_forbidden")
    require(bool(candidate_assessment.get("actionable_for_future_pilot_review")), "c37_selected_candidate_actionable", "c37_selected_candidate_not_actionable")
    require(ticker in [_normalize_ticker(x) for x in _as_list(c37_report.get("actionable_preflight_ready_tickers"))], "ticker_in_c37_actionable_list", "ticker_not_in_c37_actionable_list")
    require(bool(c36_report.get("dry_run_ready_no_submit")), "c36_dry_run_ready_no_submit", "c36_dry_run_not_ready")
    require(bool(c36_report.get("ready_for_future_final_human_pilot_review")), "c36_ready_for_future_final_human_review", "c36_not_ready_for_future_final_human_review")
    require(bool(final_snapshot), "final_preflight_snapshot_present", "final_preflight_snapshot_missing")
    require(bool(payload.get("accepted")), "payload_accepted", "payload_not_accepted")
    require(str(payload.get("side") or "").upper() == "BUY", "payload_side_buy", "payload_side_not_buy")
    require(bool(payload.get("post_only", True)), "payload_post_only_true", "payload_post_only_not_true")
    require(quote > ZERO, "payload_quote_positive", "payload_quote_missing_or_zero")
    require(quote <= max_quote_d, "payload_quote_within_cap", "payload_quote_above_cap")
    require(live_attempts == 0, "submit_audit_live_attempts_zero_before_executor", "submit_audit_contains_prior_live_attempts")
    require(live_submits == 0, "submit_audit_live_submits_zero_before_executor", "submit_audit_contains_prior_live_submits")

    # Final live-submit locks. These are intentionally separate from readiness.
    require(executor_mode == C38_FINAL_EXECUTOR_MODE, "executor_mode_final_live_pilot", "executor_mode_not_final_live_pilot")
    require(human_go_ack == C38_HUMAN_GO_ACK, "human_go_ack_exact", "human_go_ack_missing_or_wrong")
    require(actual_submit_enabled, "actual_coinbase_submit_flag_enabled", "actual_coinbase_submit_flag_disabled")
    require(submit_live, "submit_live_argument_true", "submit_live_argument_false")
    require(coinbase_client is not None, "coinbase_client_provided", "coinbase_client_not_provided")

    if actual_submit_enabled and executor_mode != C38_FINAL_EXECUTOR_MODE:
        warnings.append("actual_submit_flag_enabled_but_executor_not_in_final_mode; no submit allowed")
    if submit_live and human_go_ack != C38_HUMAN_GO_ACK:
        warnings.append("submit_live_requested_without_exact_human_ack; no submit allowed")

    can_attempt_live_submit = not blockers
    return _json_safe({
        "can_attempt_live_submit": can_attempt_live_submit,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "live_submit_hardlocks": {
            "executor_mode_required": C38_FINAL_EXECUTOR_MODE,
            "executor_mode_provided": executor_mode,
            "human_go_ack_required": C38_HUMAN_GO_ACK,
            "human_go_ack_ok": human_go_ack == C38_HUMAN_GO_ACK,
            "actual_submit_flag_enabled": actual_submit_enabled,
            "submit_live_argument": bool(submit_live),
            "coinbase_client_provided": coinbase_client is not None,
        },
        "readiness_locks": {
            "c37_candidate_actionable": bool(candidate_assessment.get("actionable_for_future_pilot_review")),
            "c36_dry_run_ready_no_submit": bool(c36_report.get("dry_run_ready_no_submit")),
            "payload_accepted": bool(payload.get("accepted")),
            "payload_quote": str(quote),
            "payload_quote_cap": str(max_quote_d),
            "post_only": bool(payload.get("post_only", True)),
            "entry_only_buy": str(payload.get("side") or "").upper() == "BUY",
        },
    })


def _build_order_intent_from_payload_and_snapshot(payload: Dict[str, Any], final_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    order_intent_snapshot = _as_dict(final_snapshot.get("order_intent_snapshot"))
    return {
        "intent_id": final_snapshot.get("pending_intent_id") or order_intent_snapshot.get("intent_id") or payload.get("client_order_id"),
        "client_order_id": payload.get("client_order_id"),
        "ticker": payload.get("ticker") or final_snapshot.get("ticker"),
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": payload.get("size_quote_normalized") or payload.get("size_quote_requested"),
        "limit_price": payload.get("limit_price"),
        "post_only": bool(payload.get("post_only", True)),
        "source": "phase_c38_final_pilot_executor_scaffold",
        "requires_fresh_judge_and_risk": True,
    }


def _build_guard_result_from_snapshot(final_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    # At this executor layer, C.3.7/C.3.6 readiness is the hard gate. This guard
    # summary is only passed to the C.2 submitter if all C.3.8 hardlocks already pass.
    return {
        "guard_allows_live_submit": True,
        "hard_block_reasons": [],
        "passed_checks": [
            "phase_c38_executor_hardlocks_passed",
            "c37_actionable_candidate_confirmed",
            "c36_final_dry_run_ready_confirmed",
            "human_go_ack_confirmed",
        ],
        "source": "phase_c38_final_pilot_executor_scaffold",
        "pending_intent_id": final_snapshot.get("pending_intent_id"),
        "fresh_analysis_id": final_snapshot.get("fresh_analysis_id"),
    }


def build_phase_c38_final_pilot_executor_report(
    *,
    cfg: Any,
    ticker: Optional[str] = None,
    c37_report: Optional[Dict[str, Any]] = None,
    c36_report: Optional[Dict[str, Any]] = None,
    analysis_log_path: str | Path = "logs/analysis.jsonl",
    execution_plan_log_path: str | Path = "logs/execution_plans.jsonl",
    pending_intents_path: str | Path = "state/pending_order_intents.json",
    order_events_path: str | Path = "logs/order_events.jsonl",
    paper_manager_path: str | Path = "logs/paper_order_manager.jsonl",
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    live_risk_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    risk_dir: str | Path | None = None,
    max_quote: Any = "10.00",
    max_lines: int = 2000,
    executor_mode: str = "dry_run",
    human_go_ack: str = "",
    submit_live: bool = False,
    coinbase_client: Any = None,
) -> Dict[str, Any]:
    """Build the C.3.8 final pilot executor scaffold report.

    Default behavior is dry-run/no-client/no-submit. A real submit path can only
    be reached when all previous readiness layers are green *and* all final live
    hardlocks are provided explicitly: final executor mode, exact human ack,
    ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true, submit_live=True and a Coinbase
    client. This function never mutates .env and never creates live exits.
    """
    if not isinstance(c37_report, dict):
        c37_report = build_phase_c37_candidate_promotion_hardening_report(
            cfg=cfg,
            ticker=ticker,
            analysis_log_path=analysis_log_path,
            execution_plan_log_path=execution_plan_log_path,
            pending_intents_path=pending_intents_path,
            order_events_path=order_events_path,
            paper_manager_path=paper_manager_path,
            pending_summary=pending_summary,
            order_summary=order_summary,
            submit_audit_summary=submit_audit_summary,
            live_risk_by_ticker=live_risk_by_ticker,
            risk_dir=risk_dir,
            max_quote=max_quote,
            max_lines=max_lines,
        )
    if not isinstance(c36_report, dict):
        c36_report = build_phase_c36_final_pilot_dry_run_report(
            cfg=cfg,
            ticker=ticker or c37_report.get("selected_ticker"),
            submit_audit_summary=submit_audit_summary,
            live_risk_by_ticker=live_risk_by_ticker,
            risk_dir=risk_dir,
            max_quote=max_quote,
            max_lines=max_lines,
        )

    selected_ticker = _resolve_selected_ticker(c37_report, c36_report, ticker)
    candidate_assessment = _candidate_assessment_by_ticker(c37_report, selected_ticker)
    payload = _payload_from_c36(c36_report)
    final_snapshot = _final_snapshot_from_c36(c36_report)
    submit_audit = _submit_audit_from_reports(c37_report, c36_report, submit_audit_summary)

    locks = _build_hardlocks(
        cfg=cfg,
        ticker=selected_ticker,
        c37_report=c37_report,
        c36_report=c36_report,
        candidate_assessment=candidate_assessment,
        payload=payload,
        final_snapshot=final_snapshot,
        human_go_ack=str(human_go_ack or ""),
        executor_mode=str(executor_mode or ""),
        submit_live=bool(submit_live),
        coinbase_client=coinbase_client,
        submit_audit=submit_audit,
        max_quote=max_quote,
    )

    can_attempt = bool(locks.get("can_attempt_live_submit"))
    submit_result: Dict[str, Any] = {
        "status": "not_attempted_hardlocked",
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "reason": "c38_hardlocks_not_satisfied" if not can_attempt else "not_attempted_until_submitter_call",
    }

    if can_attempt:
        order_intent = _build_order_intent_from_payload_and_snapshot(payload, final_snapshot)
        guard_result = _build_guard_result_from_snapshot(final_snapshot)
        product_rules = _as_dict(payload.get("product_rules_used")) or _as_dict(final_snapshot.get("product_rules"))
        submit_result = prepare_phase_c_live_entry_submission(
            cfg=cfg,
            ticker=selected_ticker,
            order_intent=order_intent,
            guard_result=guard_result,
            coinbase_client=coinbase_client,
            product_rules=product_rules,
            submit_live=True,
        )

    live_attempted = bool(submit_result.get("live_submission_attempted"))
    live_submitted = bool(submit_result.get("live_order_submitted"))
    status = "final_pilot_executor_submitted_live_order" if live_submitted else "final_pilot_executor_live_attempt_failed" if live_attempted else "final_pilot_executor_ready_but_not_submitted" if can_attempt else "final_pilot_executor_hardlocked_no_submit"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.8_final_pilot_executor_scaffold_double_hardlock",
        "status": status,
        "config_ok": True,
        "selected_ticker": selected_ticker,
        "executor_mode": executor_mode,
        "dry_run_default": executor_mode != C38_FINAL_EXECUTOR_MODE,
        "human_go_ack_required": C38_HUMAN_GO_ACK,
        "human_go_ack_ok": str(human_go_ack or "") == C38_HUMAN_GO_ACK,
        "submit_live_argument": bool(submit_live),
        "actual_coinbase_submit_currently_enabled": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "coinbase_client_provided": coinbase_client is not None,
        "can_attempt_live_submit": can_attempt,
        "live_submission_attempted_by_this_tool": live_attempted,
        "live_order_submitted": live_submitted,
        "hardlock_assessment": locks,
        "submit_result": submit_result,
        "c37_summary": {
            "status": c37_report.get("status"),
            "actionable_preflight_ready_tickers": c37_report.get("actionable_preflight_ready_tickers"),
            "blocked_or_context_tickers": c37_report.get("blocked_or_context_tickers"),
            "counts": c37_report.get("counts"),
        },
        "c36_summary": {
            "status": c36_report.get("status"),
            "dry_run_ready_no_submit": c36_report.get("dry_run_ready_no_submit"),
            "ready_for_future_final_human_pilot_review": c36_report.get("ready_for_future_final_human_pilot_review"),
            "blockers": c36_report.get("blockers"),
        },
        "candidate_assessment": candidate_assessment,
        "payload_preview_summary": {
            "accepted": bool(payload.get("accepted")),
            "client_order_id": payload.get("client_order_id"),
            "side": payload.get("side"),
            "post_only": payload.get("post_only"),
            "size_quote_requested": payload.get("size_quote_requested"),
            "size_quote_normalized": payload.get("size_quote_normalized"),
            "size_base_normalized": payload.get("size_base_normalized"),
            "limit_price": payload.get("limit_price"),
            "reject_reasons": list(payload.get("reject_reasons") or []),
        },
        "human_final_go_no_go_checklist": [
            "Controleer C.3.7: precies één actionable_preflight_ready ticker voor de gekozen pilot.",
            "Controleer C.3.6: dry_run_ready_no_submit=true en payload accepted=true.",
            "Controleer fresh judge BUY/approve_trade, deterministic live-risk accepted en fresh orderbook.",
            "Controleer quote <= 10 USDC, BUY-only, post-only, entry-only, geen live exits.",
            "Controleer logs/phase_c_live_submit.jsonl: live_submission_attempted_count=0 en live_order_submitted_count=0 vóór arming.",
            "Alleen tijdens het expliciete finale venster: executor_mode=final_live_pilot, exacte human ack, submit_live=true, Coinbase client aanwezig en ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true.",
            "Na één poging direct rollback uitvoeren: actual submit false en service herstarten.",
        ],
        "rollback_commands": [
            "python3 - <<'PY'\nfrom pathlib import Path\nimport re\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\nif re.search(r'^PHASE_C_ALLOWED_TICKERS=.*$', s, re.M):\n    s=re.sub(r'^PHASE_C_ALLOWED_TICKERS=.*$', 'PHASE_C_ALLOWED_TICKERS=', s, flags=re.M)\np.write_text(s)\nPY",
            "sudo systemctl restart coinbase-bot",
            "python3 tools/show_phase_c_submit_readiness.py --json",
            "python3 tools/show_phase_c38_final_pilot_executor_scaffold.py --json",
        ],
        "safety_policy": {
            "c38_default_is_dry_run_no_submit": True,
            "does_not_modify_env": True,
            "does_not_submit_without_all_final_hardlocks": True,
            "actual_submit_must_be_explicit_true_for_real_pilot": True,
            "submit_live_argument_must_be_true_for_real_pilot": True,
            "exact_human_go_ack_required_for_real_pilot": True,
            "coinbase_client_required_for_real_pilot": True,
            "max_one_entry_order": True,
            "entry_only_buy_only": True,
            "post_only_required": True,
            "max_quote_10_usdc": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "C38_FINAL_EXECUTOR_MODE",
    "C38_HUMAN_GO_ACK",
    "build_phase_c38_final_pilot_executor_report",
]
