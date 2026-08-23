from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bot.phase_c34_candidate_snapshot import build_phase_c34_candidate_snapshot_report


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _read_json(path: str | Path) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _extract_tickers_from_summary(summary: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(summary, dict):
        return []
    tickers: List[str] = []
    for key in ("promotion_ready", "trigger_ready", "needs_fresh_analysis", "active", "waiting", "open_intents_current"):
        items = summary.get(key)
        if isinstance(items, dict):
            items = list(items.values())
        for item in _listify(items):
            if isinstance(item, dict):
                t = _normalize_ticker(item.get("ticker"))
            else:
                t = _normalize_ticker(item)
            if t and t not in tickers:
                tickers.append(t)
    return tickers


def _load_pending_tickers_from_state(path: str | Path) -> List[str]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return []
    intents = data.get("intents")
    if isinstance(intents, dict):
        values = list(intents.values())
    elif isinstance(intents, list):
        values = intents
    else:
        values = []
    tickers: List[str] = []
    for intent in values:
        if not isinstance(intent, dict):
            continue
        status = str(intent.get("status") or "").strip().lower()
        if status in {"cancelled", "expired", "invalidated", "replaced", "failed"}:
            continue
        t = _normalize_ticker(intent.get("ticker"))
        if t and t not in tickers:
            tickers.append(t)
    return tickers


def _resolve_watch_tickers(
    *,
    cfg: Any,
    tickers: Optional[Sequence[str]] = None,
    pending_summary: Optional[Dict[str, Any]] = None,
    pending_intents_path: str | Path = "state/pending_order_intents.json",
    include_config_allowed: bool = True,
    include_pending_state: bool = True,
) -> List[str]:
    resolved: List[str] = []

    def add_many(values: Iterable[Any]) -> None:
        for value in values:
            t = _normalize_ticker(value)
            if t and t not in resolved:
                resolved.append(t)

    add_many(tickers or [])
    if include_config_allowed:
        add_many(getattr(cfg, "phase_c_allowed_tickers", []) or [])
    add_many(_extract_tickers_from_summary(pending_summary))
    if include_pending_state:
        add_many(_load_pending_tickers_from_state(pending_intents_path))
    return resolved


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


def _classify_c34_report(report: Dict[str, Any]) -> str:
    if bool(report.get("final_preflight_snapshot_ready")):
        return "preflight_ready_no_submit"
    if not bool(report.get("candidate_snapshot_extracted")):
        return "no_candidate"
    blockers = set(str(x) for x in report.get("blockers") or [])
    sources = _as_dict(report.get("sources"))
    analysis_found = bool(_as_dict(sources.get("analysis")).get("found"))
    pending_found = bool(_as_dict(sources.get("pending_intent")).get("found"))
    if not analysis_found and not pending_found:
        return "no_candidate"
    return "candidate_found_blocked"


def _minimal_candidate_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    c33 = _as_dict(report.get("c33_report"))
    c33_snapshot = _as_dict(c33.get("final_preflight_snapshot"))
    cand = _as_dict(report.get("candidate"))
    order_intent = _as_dict(cand.get("order_intent"))
    analysis = _as_dict(cand.get("analysis"))
    judge = _as_dict(analysis.get("judge"))
    return _json_safe({
        "ticker": report.get("ticker"),
        "status": report.get("status"),
        "watch_status": _classify_c34_report(report),
        "candidate_snapshot_extracted": bool(report.get("candidate_snapshot_extracted")),
        "candidate_snapshot_structural_extraction_ready": bool(report.get("candidate_snapshot_structural_extraction_ready")),
        "final_preflight_snapshot_ready": bool(report.get("final_preflight_snapshot_ready")),
        "ready_for_human_final_pilot_run_review": bool(report.get("ready_for_human_final_pilot_run_review")),
        "blockers": list(report.get("blockers") or []),
        "warnings": list(report.get("warnings") or []),
        "pending_intent_id": c33_snapshot.get("pending_intent_id") or order_intent.get("intent_id"),
        "fresh_analysis_id": c33_snapshot.get("fresh_analysis_id") or cand.get("fresh_analysis_id"),
        "judge_decision": judge.get("decision"),
        "judge_side": judge.get("side"),
        "judge_size_quote": judge.get("size_quote"),
        "order_intent_action": order_intent.get("execution_action"),
        "order_intent_side": order_intent.get("side"),
        "order_intent_limit_price": order_intent.get("limit_price"),
        "order_intent_size_quote": order_intent.get("size_quote"),
        "payload_accepted": bool(_as_dict(c33.get("payload_preview")).get("accepted")),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
    })


def build_phase_c35_candidate_watcher_report(
    *,
    cfg: Any,
    tickers: Optional[Sequence[str]] = None,
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
    include_config_allowed: bool = True,
    include_pending_state: bool = True,
) -> Dict[str, Any]:
    """Watch pilot candidates and pipe them through C.3.4 -> C.3.3.

    C.3.5 intentionally remains read-only. It does not alter .env, does not call
    Coinbase and does not submit. It merely scans chosen tickers, builds C.3.4
    snapshots where possible and reports whether any candidate has reached the
    final C.3.3 preflight-ready state.
    """
    risk_map = dict(live_risk_by_ticker or {})
    risk_map.update(_load_risk_by_ticker_from_dir(risk_dir))
    risk_map = {_normalize_ticker(k): v for k, v in risk_map.items() if isinstance(v, dict)}

    watch_tickers = _resolve_watch_tickers(
        cfg=cfg,
        tickers=tickers,
        pending_summary=pending_summary,
        pending_intents_path=pending_intents_path,
        include_config_allowed=include_config_allowed,
        include_pending_state=include_pending_state,
    )

    reports: List[Dict[str, Any]] = []
    candidate_summaries: List[Dict[str, Any]] = []
    for ticker in watch_tickers:
        risk = risk_map.get(ticker)
        c34 = build_phase_c34_candidate_snapshot_report(
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
            live_risk_result=risk,
            max_quote=max_quote,
            max_lines=max_lines,
        )
        reports.append(c34)
        candidate_summaries.append(_minimal_candidate_summary(c34))

    counts = {
        "watch_ticker_count": len(watch_tickers),
        "no_candidate": 0,
        "candidate_found_blocked": 0,
        "preflight_ready_no_submit": 0,
    }
    for item in candidate_summaries:
        status = str(item.get("watch_status") or "no_candidate")
        counts[status] = int(counts.get(status, 0)) + 1

    preflight_ready = [item for item in candidate_summaries if item.get("watch_status") == "preflight_ready_no_submit"]
    blocked_candidates = [item for item in candidate_summaries if item.get("watch_status") == "candidate_found_blocked"]
    no_candidate = [item for item in candidate_summaries if item.get("watch_status") == "no_candidate"]

    submit_audit_summary = submit_audit_summary if isinstance(submit_audit_summary, dict) else {}
    actual_submit_enabled = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    live_attempts = int(submit_audit_summary.get("live_submission_attempted_count") or 0)
    live_submits = int(submit_audit_summary.get("live_order_submitted_count") or 0)

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(watch_tickers), "watch_tickers_resolved", "no_watch_tickers_resolved")
    require(not actual_submit_enabled, "actual_coinbase_submit_disabled", "actual_coinbase_submit_enabled_forbidden")
    require(live_attempts == 0, "submit_audit_live_attempts_zero", "submit_audit_contains_live_attempts")
    require(live_submits == 0, "submit_audit_live_submits_zero", "submit_audit_contains_live_submits")
    if preflight_ready:
        passed.append("at_least_one_candidate_preflight_ready_no_submit")
    elif blocked_candidates:
        warnings.append("candidate_or_context_found_but_blocked; inspect candidate_summaries blockers")
    else:
        warnings.append("no_candidate_found_for_watch_tickers")

    status = "preflight_ready_no_submit" if preflight_ready else "candidates_blocked_or_waiting" if blocked_candidates else "no_candidate"
    if blockers:
        status = "blocked_safety_issue"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.5_candidate_watcher_preflight_pipeline",
        "status": status,
        "watch_tickers": watch_tickers,
        "counts": counts,
        "any_preflight_ready_no_submit": bool(preflight_ready),
        "preflight_ready_tickers": [item.get("ticker") for item in preflight_ready],
        "blocked_candidate_tickers": [item.get("ticker") for item in blocked_candidates],
        "no_candidate_tickers": [item.get("ticker") for item in no_candidate],
        "candidate_summaries": candidate_summaries,
        "c34_reports_by_ticker": {str(report.get("ticker")): report for report in reports},
        "actual_coinbase_submit_currently_enabled": actual_submit_enabled,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "submit_audit": {
            "live_submission_attempted_count": live_attempts,
            "live_order_submitted_count": live_submits,
            "sample_size": submit_audit_summary.get("sample_size"),
        },
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "next_step_guidance": {
            "if_no_candidate": "Laat de normale botcyclus nieuwe pending/promotion-ready context opbouwen; niet submitten.",
            "if_candidates_blocked": "Inspecteer blockers; vaak ontbreken promotion-ready status, BUY-judge, limit intent, fresh orderbook of echte live-risk approval.",
            "if_preflight_ready": "Nog steeds geen automatische submit. Ga pas door naar een aparte final pilot-run procedure met expliciete menselijke go/no-go.",
        },
        "safety_policy": {
            "c35_is_read_only_watcher": True,
            "does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_submit": True,
            "actual_submit_must_remain_false": True,
            "candidate_file_is_not_execution_permission": True,
            "fresh_judge_risk_orderbook_required": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "build_phase_c35_candidate_watcher_report",
]
