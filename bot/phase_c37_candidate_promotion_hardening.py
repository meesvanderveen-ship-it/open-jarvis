from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bot.phase_c35_candidate_watcher import build_phase_c35_candidate_watcher_report
from bot.phase_c36_final_pilot_dry_run import build_phase_c36_final_pilot_dry_run_report

ZERO = Decimal("0")
C37_MAX_QUOTE_CAP = Decimal("10.00")
BUY_DECISIONS = {"approve_trade", "buy", "enter", "open_position"}
BUY_ACTIONS = {"place_limit_buy", "limit_buy", "submit_limit_buy"}
PROMOTION_BLOCKERS = {"pending_intent_not_promotion_ready", "pending_context_not_promotion_ready"}
RISK_BLOCKERS = {"live_risk_result_not_supplied_or_not_found", "live_risk_approval_missing", "risk_result_is_paper_not_live"}


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


def _read_json(path: str | Path) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_risk_by_ticker_from_dir(risk_dir: str | Path | None) -> Dict[str, Dict[str, Any]]:
    if not risk_dir:
        return {}
    root = Path(risk_dir)
    if not root.exists() or not root.is_dir():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        ticker = _normalize_ticker(data.get("ticker") or path.stem.replace("_risk", "").replace("-risk", ""))
        if ticker:
            out[ticker] = data
    return out


def _normalize_risk_map(
    live_risk_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    risk_dir: str | Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    risk_map: Dict[str, Dict[str, Any]] = {}
    for key, value in (live_risk_by_ticker or {}).items():
        if isinstance(value, dict):
            risk_map[_normalize_ticker(key)] = value
    risk_map.update(_load_risk_by_ticker_from_dir(risk_dir))
    return {k: v for k, v in risk_map.items() if k and isinstance(v, dict)}


def _risk_is_live_accepted(risk: Dict[str, Any]) -> bool:
    if not isinstance(risk, dict) or not risk:
        return False
    accepted = bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved"))
    mode = str(risk.get("mode") or risk.get("risk_mode") or "").lower()
    if not accepted:
        return False
    if "paper" in mode or "dry" in mode or "shadow" in mode:
        return False
    return True


def summarize_phase_c37_live_risk_bridge(
    *,
    live_risk_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    risk_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """Summarize externally supplied deterministic live-risk snapshots.

    This bridge only classifies supplied JSON. It does not run risk checks itself,
    does not approve trades and does not call Coinbase.
    """
    risk_map = _normalize_risk_map(live_risk_by_ticker, risk_dir)
    accepted: List[str] = []
    blocked: List[Dict[str, Any]] = []
    for ticker, risk in sorted(risk_map.items()):
        if _risk_is_live_accepted(risk):
            accepted.append(ticker)
        else:
            blocked.append({
                "ticker": ticker,
                "accepted": bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved")),
                "mode": risk.get("mode") or risk.get("risk_mode"),
                "reason": risk.get("reason") or risk.get("message") or "risk_snapshot_not_live_accepted",
            })
    return _json_safe({
        "risk_snapshot_source": str(risk_dir) if risk_dir else "provided_map" if live_risk_by_ticker else "none",
        "supplied_tickers": sorted(risk_map.keys()),
        "accepted_live_risk_tickers": accepted,
        "blocked_or_non_live_risk": blocked,
        "count_supplied": len(risk_map),
        "count_accepted_live": len(accepted),
        "safety_policy": {
            "does_not_fabricate_live_risk": True,
            "risk_snapshot_is_not_execution_permission": True,
            "still_requires_c33_c35_c36_green": True,
        },
    })


def _blocker_categories(blockers: Iterable[Any], summary: Dict[str, Any]) -> List[str]:
    blockers_s = {str(x) for x in blockers if str(x)}
    categories: List[str] = []
    if blockers_s & PROMOTION_BLOCKERS:
        categories.append("pending_intent_not_promotion_ready")
    if blockers_s & RISK_BLOCKERS:
        categories.append("live_risk_missing_or_not_live")
    decision = str(summary.get("judge_decision") or "").lower()
    side = str(summary.get("judge_side") or "").upper()
    action = str(summary.get("order_intent_action") or "").lower()
    order_side = str(summary.get("order_intent_side") or "").upper()
    quote = _to_decimal(summary.get("order_intent_size_quote") or summary.get("judge_size_quote"), "0")
    if decision not in BUY_DECISIONS or side != "BUY":
        categories.append("judge_not_buy_approval")
    if action not in BUY_ACTIONS or order_side != "BUY":
        categories.append("order_intent_not_place_limit_buy")
    if quote <= ZERO:
        categories.append("quote_size_missing_or_zero")
    elif quote > C37_MAX_QUOTE_CAP:
        categories.append("quote_size_above_10_usdc_cap")
    if not bool(summary.get("payload_accepted")):
        categories.append("payload_not_accepted")
    # Preserve unknown blocker strings as diagnostic categories, but keep known
    # categories first so the CLI output stays readable.
    known = set(PROMOTION_BLOCKERS | RISK_BLOCKERS)
    for blocker in sorted(blockers_s - known):
        if blocker not in categories:
            categories.append(blocker)
    # De-duplicate while preserving order.
    out: List[str] = []
    for item in categories:
        if item and item not in out:
            out.append(item)
    return out


def assess_phase_c37_candidate_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a C.3.5 candidate summary for final-pilot promotion.

    This intentionally treats only C.3.5 `preflight_ready_no_submit` candidates as
    actionable. WAIT/NONE/no_order candidates are reported as blocked context and
    their payload previews should not be shown as executable previews.
    """
    summary_d = _as_dict(summary)
    ticker = _normalize_ticker(summary_d.get("ticker"))
    watch_status = str(summary_d.get("watch_status") or "").strip().lower()
    blockers = list(summary_d.get("blockers") or [])
    categories = _blocker_categories(blockers, summary_d)
    decision = str(summary_d.get("judge_decision") or "").lower()
    side = str(summary_d.get("judge_side") or "").upper()
    action = str(summary_d.get("order_intent_action") or "").lower()
    order_side = str(summary_d.get("order_intent_side") or "").upper()
    quote = _to_decimal(summary_d.get("order_intent_size_quote") or summary_d.get("judge_size_quote"), "0")
    payload_accepted = bool(summary_d.get("payload_accepted"))
    actionable = (
        watch_status == "preflight_ready_no_submit"
        and decision in BUY_DECISIONS
        and side == "BUY"
        and action in BUY_ACTIONS
        and order_side == "BUY"
        and quote > ZERO
        and quote <= C37_MAX_QUOTE_CAP
        and payload_accepted
        and not blockers
    )
    suppress_payload_preview = not actionable
    return _json_safe({
        "ticker": ticker,
        "watch_status": watch_status or "unknown",
        "promotion_status": "actionable_preflight_ready_no_submit" if actionable else "blocked_or_context_only",
        "actionable_for_future_pilot_review": actionable,
        "payload_preview_should_be_suppressed": suppress_payload_preview,
        "payload_preview_suppression_reason": None if actionable else "candidate_not_actionable_buy_preflight_ready",
        "blocker_categories": categories,
        "raw_blockers": blockers,
        "judge_decision": summary_d.get("judge_decision"),
        "judge_side": summary_d.get("judge_side"),
        "judge_size_quote": summary_d.get("judge_size_quote"),
        "order_intent_action": summary_d.get("order_intent_action"),
        "order_intent_side": summary_d.get("order_intent_side"),
        "order_intent_size_quote": summary_d.get("order_intent_size_quote"),
        "payload_accepted": payload_accepted,
        "safety_policy": {
            "blocked_candidate_payload_is_not_executable": True,
            "pending_intent_context_only": True,
            "requires_preflight_ready_no_submit": True,
        },
    })


def _candidate_summary_by_ticker(c35_report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    ticker_n = _normalize_ticker(ticker)
    for item in _as_list(c35_report.get("candidate_summaries")):
        if isinstance(item, dict) and _normalize_ticker(item.get("ticker")) == ticker_n:
            return item
    return {}


def _safe_c36_preview(c36_report: Dict[str, Any], selected_assessment: Dict[str, Any]) -> Dict[str, Any]:
    final_preview = _as_dict(c36_report.get("final_run_preview"))
    payload = _as_dict(final_preview.get("payload_preview"))
    actionable = bool(selected_assessment.get("actionable_for_future_pilot_review"))
    if not payload:
        return {"payload_preview_present": False, "payload_preview_suppressed": True, "reason": "no_payload_preview_present"}
    if actionable and bool(payload.get("accepted")):
        return {
            "payload_preview_present": True,
            "payload_preview_suppressed": False,
            "payload_preview": payload,
            "reason": "candidate_actionable_preflight_ready_no_submit",
        }
    return {
        "payload_preview_present": True,
        "payload_preview_suppressed": True,
        "payload_preview_summary_only": {
            "accepted": bool(payload.get("accepted")),
            "client_order_id": payload.get("client_order_id"),
            "reject_reasons": list(payload.get("reject_reasons") or []),
            "size_quote_requested": payload.get("size_quote_requested"),
            "size_quote_normalized": payload.get("size_quote_normalized"),
            "size_base_normalized": payload.get("size_base_normalized"),
        },
        "reason": "blocked_candidate_payload_preview_is_diagnostic_only_not_executable",
    }


def _resolve_selected_ticker(c35_report: Dict[str, Any], ticker: Optional[str]) -> str:
    requested = _normalize_ticker(ticker)
    if requested:
        return requested
    ready = [_normalize_ticker(x) for x in _as_list(c35_report.get("preflight_ready_tickers")) if _normalize_ticker(x)]
    if ready:
        return ready[0]
    watch = [_normalize_ticker(x) for x in _as_list(c35_report.get("watch_tickers")) if _normalize_ticker(x)]
    return watch[0] if watch else ""


def build_phase_c37_candidate_promotion_hardening_report(
    *,
    cfg: Any,
    tickers: Optional[Sequence[str]] = None,
    ticker: Optional[str] = None,
    c35_report: Optional[Dict[str, Any]] = None,
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
) -> Dict[str, Any]:
    """Build C.3.7 candidate promotion hardening + live-risk bridge report.

    C.3.7 is a larger read-only hardening layer over C.3.5/C.3.6. It verifies
    that only real preflight-ready BUY candidates are allowed to look like future
    pilot candidates, summarizes live-risk snapshots supplied by external risk
    code, and suppresses diagnostic zero-size payload previews for blocked
    WAIT/no_order candidates.
    """
    risk_bridge = summarize_phase_c37_live_risk_bridge(live_risk_by_ticker=live_risk_by_ticker, risk_dir=risk_dir)
    if not isinstance(c35_report, dict):
        risk_map = _normalize_risk_map(live_risk_by_ticker, risk_dir)
        c35_report = build_phase_c35_candidate_watcher_report(
            cfg=cfg,
            tickers=tickers or ([ticker] if ticker else None),
            analysis_log_path=analysis_log_path,
            execution_plan_log_path=execution_plan_log_path,
            pending_intents_path=pending_intents_path,
            order_events_path=order_events_path,
            paper_manager_path=paper_manager_path,
            pending_summary=pending_summary,
            order_summary=order_summary,
            submit_audit_summary=submit_audit_summary,
            live_risk_by_ticker=risk_map,
            max_quote=max_quote,
            max_lines=max_lines,
        )

    selected_ticker = _resolve_selected_ticker(c35_report, ticker)
    if not isinstance(c36_report, dict):
        c36_report = build_phase_c36_final_pilot_dry_run_report(
            cfg=cfg,
            ticker=selected_ticker or ticker,
            c35_report=c35_report,
            submit_audit_summary=submit_audit_summary,
            max_quote=max_quote,
        )

    assessments = [assess_phase_c37_candidate_summary(item) for item in _as_list(c35_report.get("candidate_summaries")) if isinstance(item, dict)]
    actionable = [a for a in assessments if a.get("actionable_for_future_pilot_review")]
    blocked = [a for a in assessments if not a.get("actionable_for_future_pilot_review")]
    selected_summary = _candidate_summary_by_ticker(c35_report, selected_ticker)
    selected_assessment = assess_phase_c37_candidate_summary(selected_summary) if selected_summary else {}

    submit_audit = _as_dict(c35_report.get("submit_audit")) or _as_dict(submit_audit_summary)
    live_attempts = int(submit_audit.get("live_submission_attempted_count") or 0)
    live_submits = int(submit_audit.get("live_order_submitted_count") or 0)
    actual_submit_enabled = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(not actual_submit_enabled, "actual_coinbase_submit_disabled", "actual_coinbase_submit_enabled_forbidden_in_c37")
    require(live_attempts == 0, "submit_audit_live_attempts_zero", "submit_audit_contains_live_attempts")
    require(live_submits == 0, "submit_audit_live_submits_zero", "submit_audit_contains_live_submits")
    require(not bool(c36_report.get("live_submission_attempted_by_this_tool")), "c36_made_no_live_attempt", "c36_attempted_live_submit_forbidden")
    require(not bool(c36_report.get("live_order_submitted")), "c36_submitted_no_live_order", "c36_submitted_live_order_forbidden")
    require(bool(c35_report.get("watch_tickers")), "watch_tickers_available", "no_watch_tickers_available")

    if actionable:
        passed.append("at_least_one_actionable_preflight_candidate")
    elif blocked:
        warnings.append("no_actionable_candidates_yet; blocked_context_only")
    else:
        warnings.append("no_candidates_or_context_found")

    if selected_assessment and selected_assessment.get("payload_preview_should_be_suppressed"):
        passed.append("blocked_candidate_payload_preview_suppressed_by_c37")

    safe_preview = _safe_c36_preview(c36_report, selected_assessment)
    status = "actionable_preflight_candidates_ready_no_submit" if actionable and not blockers else "no_actionable_candidates_yet" if not blockers else "blocked_safety_issue"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.7_candidate_promotion_hardening_live_risk_bridge",
        "status": status,
        "config_ok": True,
        "selected_ticker": selected_ticker,
        "actionable_preflight_ready_tickers": [a.get("ticker") for a in actionable],
        "blocked_or_context_tickers": [a.get("ticker") for a in blocked],
        "counts": {
            "watch_ticker_count": len(_as_list(c35_report.get("watch_tickers"))),
            "actionable_preflight_ready": len(actionable),
            "blocked_or_context_only": len(blocked),
        },
        "actual_coinbase_submit_currently_enabled": actual_submit_enabled,
        "actual_coinbase_submit_must_remain_false_in_c37": True,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "live_risk_bridge": risk_bridge,
        "candidate_assessments": assessments,
        "selected_candidate_assessment": selected_assessment,
        "safe_c36_payload_preview": safe_preview,
        "c35_summary": {
            "status": c35_report.get("status"),
            "watch_tickers": c35_report.get("watch_tickers"),
            "counts": c35_report.get("counts"),
            "preflight_ready_tickers": c35_report.get("preflight_ready_tickers"),
            "blocked_candidate_tickers": c35_report.get("blocked_candidate_tickers"),
            "any_preflight_ready_no_submit": c35_report.get("any_preflight_ready_no_submit"),
        },
        "c36_summary": {
            "status": c36_report.get("status"),
            "dry_run_ready_no_submit": c36_report.get("dry_run_ready_no_submit"),
            "ready_for_future_final_human_pilot_review": c36_report.get("ready_for_future_final_human_pilot_review"),
            "blockers": c36_report.get("blockers"),
        },
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "next_step_guidance": {
            "if_no_actionable_candidates": "Niet armeren. Laat normale botcyclus nieuwe promotion-ready BUY-kandidaat plus echte live-risk snapshot opbouwen.",
            "if_actionable_preflight_ready": "Nog steeds niet automatisch submitten. Gebruik C.3.6 runbook en daarna pas aparte final pilot-run met expliciete menselijke go/no-go.",
            "risk_bridge": "Lever echte deterministic live-risk JSON via --risk-dir of live_risk_by_ticker; C.3.7 verzint dit nooit.",
        },
        "safety_policy": {
            "c37_is_read_only_hardening": True,
            "does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_submit": True,
            "actual_submit_must_remain_false": True,
            "blocked_payload_preview_is_diagnostic_only": True,
            "does_not_fabricate_live_risk": True,
            "fresh_judge_risk_orderbook_required": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "assess_phase_c37_candidate_summary",
    "build_phase_c37_candidate_promotion_hardening_report",
    "summarize_phase_c37_live_risk_bridge",
]
