from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bot.phase_c35_candidate_watcher import build_phase_c35_candidate_watcher_report

ZERO = Decimal("0")
C36_MAX_QUOTE_CAP = Decimal("10.00")


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


def _candidate_summary_by_ticker(c35_report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker)
    for item in _as_list(c35_report.get("candidate_summaries")):
        if isinstance(item, dict) and _normalize_ticker(item.get("ticker")) == ticker_n:
            return item
    return {}


def _c34_report_by_ticker(c35_report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker)
    reports = _as_dict(c35_report.get("c34_reports_by_ticker"))
    for key, value in reports.items():
        if _normalize_ticker(key) == ticker_n and isinstance(value, dict):
            return value
    return {}


def _payload_from_c34(c34_report: Dict[str, Any]) -> Dict[str, Any]:
    c33 = _as_dict(c34_report.get("c33_report"))
    payload = _as_dict(c33.get("payload_preview"))
    return payload


def _final_snapshot_from_c34(c34_report: Dict[str, Any]) -> Dict[str, Any]:
    c33 = _as_dict(c34_report.get("c33_report"))
    return _as_dict(c33.get("final_preflight_snapshot"))


def _resolve_selected_ticker(c35_report: Dict[str, Any], ticker: Optional[str]) -> str:
    requested = _normalize_ticker(ticker)
    if requested:
        return requested
    ready = [_normalize_ticker(x) for x in _as_list(c35_report.get("preflight_ready_tickers")) if _normalize_ticker(x)]
    return ready[0] if ready else ""


def _build_c36_env_preview(ticker: str, max_quote: Any = "10.00") -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker) or "<KIES-ÉÉN-TICKER>"
    max_quote_s = str(_to_decimal(max_quote, "10.00") or C36_MAX_QUOTE_CAP)
    return {
        "staged_preflight_env_lines": [
            "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
            "ENABLE_LIVE_LIMIT_ORDERS=true",
            "ENABLE_LIVE_ENTRY_ORDERS=true",
            "ENABLE_LIVE_EXIT_ORDERS=false",
            "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true",
            "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
            f"PHASE_C_ALLOWED_TICKERS={ticker_n}",
            f"PHASE_C_MAX_ORDER_QUOTE={max_quote_s}",
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
        ],
        "final_actual_submit_arm_line_not_for_c36": "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true",
        "rollback_env_lines": [
            "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
            "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=false",
            "ENABLE_LIVE_LIMIT_ORDERS=false",
            "ENABLE_LIVE_ENTRY_ORDERS=false",
            "ENABLE_LIVE_EXIT_ORDERS=false",
            "PHASE_C_ALLOWED_TICKERS=",
        ],
        "safety_note": "C.3.6 toont alleen runbook/preview. Deze module wijzigt geen .env en plaatst geen orders.",
    }


def _build_human_checklist(ticker: str) -> List[str]:
    ticker_n = _normalize_ticker(ticker) or "<ticker>"
    return [
        f"Controleer dat C.3.5 preflight_ready_no_submit toont voor exact {ticker_n}.",
        "Controleer dat candidate_summaries één BUY-kandidaat tonen met judge approve_trade, side BUY en quote <= 10 USDC.",
        "Controleer dat C.3.3 final_preflight_snapshot_ready=true en payload_accepted=true toont.",
        "Controleer dat ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false blijft tijdens C.3.6 dry-run.",
        "Controleer logs/phase_c_live_submit.jsonl: live_submission_attempted_count=0 en live_order_submitted_count=0 vóór elk later go-moment.",
        "Controleer dat live exit-orders uit blijven en followers niet meedoen aan order-lifecycle.",
        "Controleer post-only, limit_price, expiry en product increments/min-size in de payload preview.",
        "Plan rollback vóór een eventuele latere echte pilot: actual submit direct terug naar false en service herstarten.",
    ]


def _build_monitoring_commands(ticker: str) -> List[str]:
    ticker_n = _normalize_ticker(ticker) or "BTC-USDC"
    return [
        f"python3 tools/show_phase_c35_candidate_watcher.py --ticker {ticker_n} --json",
        f"python3 tools/show_phase_c36_final_pilot_dry_run.py --ticker {ticker_n} --json",
        "python3 tools/show_phase_c_submit_readiness.py --json",
        "journalctl -u coinbase-bot -f",
        "tail -f logs/phase_c_live_submit.jsonl logs/order_events.jsonl logs/errors.jsonl",
    ]


def _build_rollback_commands() -> List[str]:
    return [
        "python3 - <<'PY'\nfrom pathlib import Path\nimport re\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\nif re.search(r'^PHASE_C_ALLOWED_TICKERS=.*$', s, re.M):\n    s=re.sub(r'^PHASE_C_ALLOWED_TICKERS=.*$', 'PHASE_C_ALLOWED_TICKERS=', s, flags=re.M)\np.write_text(s)\nPY",
        "sudo systemctl restart coinbase-bot",
        "python3 tools/show_phase_c_submit_readiness.py --json",
        "python3 tools/show_phase_c35_candidate_watcher.py --json",
    ]


def build_phase_c36_final_pilot_dry_run_report(
    *,
    cfg: Any,
    ticker: Optional[str] = None,
    c35_report: Optional[Dict[str, Any]] = None,
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
    require_human_go_ack: bool = False,
) -> Dict[str, Any]:
    """Build the C.3.6 final pilot-run dry-run/runbook report.

    C.3.6 deliberately remains a hardlocked dry-run stage. It consumes the C.3.5
    watcher/preflight pipeline, selects a preflight-ready candidate when present,
    and prepares the human go/no-go checklist and rollback/monitoring runbook.
    It never modifies .env, never calls Coinbase and never submits an order.
    """
    if not isinstance(c35_report, dict):
        c35_report = build_phase_c35_candidate_watcher_report(
            cfg=cfg,
            tickers=[ticker] if ticker else None,
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

    selected_ticker = _resolve_selected_ticker(c35_report, ticker)
    selected_summary = _candidate_summary_by_ticker(c35_report, selected_ticker) if selected_ticker else {}
    selected_c34 = _c34_report_by_ticker(c35_report, selected_ticker) if selected_ticker else {}
    payload_preview = _payload_from_c34(selected_c34)
    final_snapshot = _final_snapshot_from_c34(selected_c34)

    submit_audit = _as_dict(c35_report.get("submit_audit")) or _as_dict(submit_audit_summary)
    live_attempts = int(submit_audit.get("live_submission_attempted_count") or 0)
    live_submits = int(submit_audit.get("live_order_submitted_count") or 0)
    actual_submit_enabled = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    payload_accepted = bool(payload_preview.get("accepted"))
    quote = _to_decimal(payload_preview.get("size_quote_normalized") or payload_preview.get("size_quote_requested"), "0")
    preflight_ready_tickers = [_normalize_ticker(x) for x in _as_list(c35_report.get("preflight_ready_tickers"))]
    selected_is_preflight_ready = bool(selected_ticker and selected_ticker in preflight_ready_tickers)

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(selected_ticker), "pilot_ticker_selected", "pilot_ticker_not_selected")
    require(not actual_submit_enabled, "actual_coinbase_submit_currently_disabled", "actual_coinbase_submit_enabled_forbidden_in_c36")
    require(live_attempts == 0, "submit_audit_live_attempts_zero", "submit_audit_contains_live_attempts")
    require(live_submits == 0, "submit_audit_live_submits_zero", "submit_audit_contains_live_submits")
    require(bool(c35_report.get("any_preflight_ready_no_submit")), "c35_has_preflight_ready_candidate", "c35_has_no_preflight_ready_candidate")
    require(selected_is_preflight_ready, "selected_ticker_is_preflight_ready", "selected_ticker_not_preflight_ready")
    require(bool(selected_summary), "selected_candidate_summary_found", "selected_candidate_summary_missing")
    require(bool(selected_c34), "selected_c34_report_found", "selected_c34_report_missing")
    require(bool(final_snapshot), "final_preflight_snapshot_available", "final_preflight_snapshot_missing")
    require(payload_accepted, "payload_preview_accepted", "payload_preview_not_accepted")
    require(quote > ZERO and quote <= C36_MAX_QUOTE_CAP, "payload_quote_within_10_usdc_cap", "payload_quote_missing_or_above_cap")
    require(str(payload_preview.get("side") or "").upper() == "BUY", "payload_side_buy", "payload_side_not_buy")
    require(bool(payload_preview.get("post_only", True)), "payload_post_only_true", "payload_post_only_not_true")

    if not require_human_go_ack:
        warnings.append("human_go_ack_not_required_in_c36_dry_run; later real pilot must require explicit human go/no-go")
    else:
        passed.append("human_go_ack_recorded_for_dry_run_review_only")

    dry_run_ready = not blockers
    status = "final_pilot_run_dry_run_ready_no_submit" if dry_run_ready else "final_pilot_run_dry_run_blocked"

    final_run_preview = {
        "selected_ticker": selected_ticker,
        "candidate_summary": selected_summary,
        "final_preflight_snapshot": final_snapshot,
        "payload_preview": payload_preview,
        "would_submit_if_future_final_go_enabled": bool(dry_run_ready),
        "submit_live_argument_for_c36": False,
        "coinbase_client_for_c36": None,
        "actual_submit_required_for_future_real_pilot": True,
        "actual_submit_currently_enabled": actual_submit_enabled,
    }

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.6_final_pilot_run_dry_run_hardlock_runbook",
        "status": status,
        "config_ok": True,
        "selected_ticker": selected_ticker,
        "dry_run_ready_no_submit": dry_run_ready,
        "ready_for_future_final_human_pilot_review": dry_run_ready,
        "actual_coinbase_submit_currently_enabled": actual_submit_enabled,
        "actual_coinbase_submit_must_remain_false_in_c36": True,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "c35_summary": {
            "status": c35_report.get("status"),
            "watch_tickers": c35_report.get("watch_tickers"),
            "counts": c35_report.get("counts"),
            "preflight_ready_tickers": c35_report.get("preflight_ready_tickers"),
            "blocked_candidate_tickers": c35_report.get("blocked_candidate_tickers"),
            "any_preflight_ready_no_submit": c35_report.get("any_preflight_ready_no_submit"),
        },
        "selected_candidate_summary": selected_summary,
        "final_run_preview": final_run_preview,
        "human_go_no_go_checklist": _build_human_checklist(selected_ticker),
        "env_preview": _build_c36_env_preview(selected_ticker, max_quote=max_quote),
        "monitoring_commands": _build_monitoring_commands(selected_ticker),
        "rollback_commands": _build_rollback_commands(),
        "next_step_guidance": {
            "if_blocked": "Niet armeren. Wacht op C.3.5 preflight_ready_no_submit en los blockers op.",
            "if_dry_run_ready": "Nog steeds geen automatische submit. Volgende fase is een aparte final pilot-run met expliciete menselijke go/no-go en directe rollback.",
            "actual_submit_line_forbidden_in_c36": "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true hoort niet in C.3.6 dry-run.",
        },
        "safety_policy": {
            "c36_is_dry_run_runbook_only": True,
            "does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_submit": True,
            "submit_live_argument_false": True,
            "coinbase_client_not_provided": True,
            "actual_submit_must_remain_false": True,
            "candidate_file_is_not_execution_permission": True,
            "fresh_judge_risk_orderbook_required": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "build_phase_c36_final_pilot_dry_run_report",
]
