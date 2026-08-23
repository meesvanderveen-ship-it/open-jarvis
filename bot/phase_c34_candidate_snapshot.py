from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.phase_c33_candidate_preflight import build_phase_c33_final_preflight_report

ZERO = Decimal("0")
C34_MAX_QUOTE_CAP = Decimal("10.00")
ACTIVE_PENDING_STATUSES = {"active", "waiting", "trigger_ready", "needs_fresh_analysis", "stale"}
PROMOTION_READY_STATUSES = {"trigger_ready", "needs_fresh_analysis"}


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: str | Path) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _iter_jsonl_reverse(path: str | Path, *, max_lines: int = 2000) -> Iterable[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    count = 0
    out: List[Dict[str, Any]] = []
    for line in reversed(lines):
        if count >= max_lines:
            break
        count += 1
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _latest_jsonl_for_ticker(path: str | Path, ticker: str, *, max_lines: int = 2000) -> Optional[Dict[str, Any]]:
    ticker_n = _normalize_ticker(ticker)
    for obj in _iter_jsonl_reverse(path, max_lines=max_lines):
        if _normalize_ticker(obj.get("ticker")) == ticker_n:
            return obj
        intent = obj.get("intent") if isinstance(obj.get("intent"), dict) else {}
        if _normalize_ticker(intent.get("ticker")) == ticker_n:
            return obj
    return None


def _latest_order_intent_for_ticker(*, ticker: str, order_events_path: str | Path, paper_manager_path: str | Path, max_lines: int = 2000) -> Optional[Dict[str, Any]]:
    ticker_n = _normalize_ticker(ticker)
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    for path in (order_events_path, paper_manager_path):
        for obj in _iter_jsonl_reverse(path, max_lines=max_lines):
            intent = obj.get("intent") if isinstance(obj.get("intent"), dict) else None
            if not isinstance(intent, dict):
                continue
            if _normalize_ticker(intent.get("ticker")) != ticker_n:
                continue
            action = str(intent.get("execution_action") or "").strip().lower()
            side = str(intent.get("side") or "").strip().upper()
            status = str(intent.get("status") or "").strip().lower()
            # Only use an actionable, non-diagnostic paper intent as source material.
            if action == "place_limit_buy" and side == "BUY" and status not in {"failed", "rejected", "cancelled"}:
                ts = str(obj.get("generated_at") or intent.get("created_at") or intent.get("updated_at") or "")
                candidates.append((ts, intent))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _load_pending_intents(path: str | Path) -> List[Dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return []
    intents = data.get("intents")
    if isinstance(intents, dict):
        return [dict(v) for v in intents.values() if isinstance(v, dict)]
    if isinstance(intents, list):
        return [dict(v) for v in intents if isinstance(v, dict)]
    return []


def _intent_is_promotion_ready(intent: Dict[str, Any]) -> bool:
    status = str(intent.get("status") or "").strip().lower()
    if status in PROMOTION_READY_STATUSES:
        return True
    last = intent.get("last_evaluation") if isinstance(intent.get("last_evaluation"), dict) else {}
    return _truthy(last.get("trigger_ready")) or _truthy(intent.get("trigger_ready"))


def _latest_pending_intent_for_ticker(path: str | Path, ticker: str) -> Optional[Dict[str, Any]]:
    ticker_n = _normalize_ticker(ticker)
    candidates: List[Dict[str, Any]] = []
    for intent in _load_pending_intents(path):
        if _normalize_ticker(intent.get("ticker")) != ticker_n:
            continue
        status = str(intent.get("status") or "active").strip().lower()
        if status not in ACTIVE_PENDING_STATUSES:
            continue
        candidates.append(intent)
    if not candidates:
        return None
    candidates.sort(key=lambda x: str(x.get("updated_at") or x.get("last_seen_at") or x.get("created_at") or ""), reverse=True)
    # Prefer promotion-ready but keep latest active as context if none are ready.
    ready = [x for x in candidates if _intent_is_promotion_ready(x)]
    return (ready or candidates)[0]


def _pending_context_from_intent(intent: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(intent, dict):
        return {}
    status = str(intent.get("status") or "").strip().lower()
    last = intent.get("last_evaluation") if isinstance(intent.get("last_evaluation"), dict) else {}
    trigger_ready = _truthy(intent.get("trigger_ready")) or _truthy(last.get("trigger_ready")) or status in PROMOTION_READY_STATUSES
    return _json_safe({
        "intent_id": intent.get("intent_id") or intent.get("id"),
        "ticker": _normalize_ticker(intent.get("ticker")),
        "status": status,
        "trigger_ready": trigger_ready,
        "requires_fresh_judge_and_risk": True,
        "reason": last.get("reason") or intent.get("reason"),
        "current_price": last.get("current_price") or intent.get("current_price_at_creation"),
        "source_kind": intent.get("source_kind"),
        "created_at": intent.get("created_at"),
        "updated_at": intent.get("updated_at"),
    })


def _analysis_id(analysis: Dict[str, Any]) -> str:
    for key in ("analysis_id", "fresh_analysis_id", "run_id", "cycle_id"):
        if analysis.get(key):
            return str(analysis.get(key))
    ticker = _normalize_ticker(analysis.get("ticker")) or "UNKNOWN"
    ts = str(analysis.get("generated_at") or "unknown-time")
    return f"analysis-{ticker}-{ts}"


def _market_product_rules(analysis: Dict[str, Any]) -> Dict[str, Any]:
    fp = analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else {}
    market = fp.get("market") if isinstance(fp.get("market"), dict) else {}
    return {
        "base_increment": market.get("base_increment") or "0.00000001",
        "quote_increment": market.get("quote_increment") or "0.01",
        "base_min_size": market.get("base_min_size") or "0.00000001",
        "quote_min_size": market.get("quote_min_size") or "1",
    }


def _normalize_orderbook_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    ob = deepcopy(plan.get("orderbook_summary") if isinstance(plan.get("orderbook_summary"), dict) else {})
    tob = ob.get("top_of_book") if isinstance(ob.get("top_of_book"), dict) else {}
    if "best_bid" not in ob and tob.get("best_bid") is not None:
        ob["best_bid"] = tob.get("best_bid")
    if "best_ask" not in ob and tob.get("best_ask") is not None:
        ob["best_ask"] = tob.get("best_ask")
    if "spread_pct" not in ob and tob.get("spread_pct") is not None:
        ob["spread_pct"] = tob.get("spread_pct")
    return ob


def _derive_limit_price(order_intent: Dict[str, Any], plan: Dict[str, Any]) -> Decimal:
    price = _to_decimal(order_intent.get("limit_price"), "0")
    if price > ZERO:
        return price
    ob = _normalize_orderbook_summary(plan)
    # Conservative post-only buy preview: prefer best bid if present, else mid/limit from intent.
    for key in ("best_bid", "mid_price", "best_ask"):
        val = _to_decimal(ob.get(key), "0")
        if val > ZERO:
            return val
    return ZERO


def _derive_order_intent(*, ticker: str, analysis: Dict[str, Any], execution_plan: Dict[str, Any], logged_intent: Optional[Dict[str, Any]], max_quote: Any) -> Dict[str, Any]:
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    source_intent = deepcopy(logged_intent) if isinstance(logged_intent, dict) else {}
    if not source_intent and isinstance(analysis.get("paper_order"), dict):
        source_intent = deepcopy(analysis.get("paper_order"))

    action = str(source_intent.get("execution_action") or execution_plan.get("execution_action") or "").strip().lower()
    side = str(source_intent.get("side") or judge.get("side") or "").strip().upper()
    quote = _to_decimal(source_intent.get("size_quote") or judge.get("size_quote") or judge.get("quote_size"), "0")
    max_quote_d = _to_decimal(max_quote, "10.00")
    if quote > max_quote_d:
        quote = max_quote_d
    limit_price = _derive_limit_price(source_intent, execution_plan)
    expiry_minutes = int(_to_decimal(source_intent.get("expiry_minutes") or execution_plan.get("expiry_minutes"), "60"))
    return _json_safe({
        "ticker": _normalize_ticker(ticker),
        "side": side or "BUY",
        "execution_action": action,
        "order_type": source_intent.get("order_type") or "limit",
        "size_quote": str(quote) if quote > ZERO else None,
        "limit_price": str(limit_price) if limit_price > ZERO else None,
        "expiry_minutes": expiry_minutes,
        "intent_id": source_intent.get("intent_id") or source_intent.get("linked_trade_plan_id"),
        "source": "phase_c34_candidate_snapshot_extractor",
    })


def _merge_pending_context(analysis: Dict[str, Any], pending_ctx: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(analysis)
    if not pending_ctx:
        return out
    fp = out.setdefault("feature_pack", {})
    if not isinstance(fp, dict):
        fp = {}
        out["feature_pack"] = fp
    decision_context = fp.setdefault("decision_context", {})
    if not isinstance(decision_context, dict):
        decision_context = {}
        fp["decision_context"] = decision_context
    decision_context["pending_order_intent"] = pending_ctx
    out["paper_pending_order_intent"] = pending_ctx
    return out


def build_phase_c34_candidate_from_sources(
    *,
    ticker: str,
    analysis: Optional[Dict[str, Any]],
    execution_plan: Optional[Dict[str, Any]],
    pending_intent: Optional[Dict[str, Any]],
    logged_order_intent: Optional[Dict[str, Any]] = None,
    live_risk_result: Optional[Dict[str, Any]] = None,
    max_quote: Any = "10.00",
) -> Dict[str, Any]:
    """Build a C.3.3-compatible candidate snapshot from existing bot artifacts.

    The builder is intentionally conservative. It never fabricates deterministic
    live risk approval. If no live_risk_result is supplied/found, the generated
    candidate remains structurally incomplete and C.3.3 must block it.
    """
    ticker_n = _normalize_ticker(ticker)
    analysis_d = deepcopy(analysis) if isinstance(analysis, dict) else {}
    plan_d = deepcopy(execution_plan) if isinstance(execution_plan, dict) else {}
    pending_ctx = _pending_context_from_intent(pending_intent)
    analysis_d = _merge_pending_context(analysis_d, pending_ctx)
    plan_d["orderbook_summary"] = _normalize_orderbook_summary(plan_d)
    order_intent = _derive_order_intent(
        ticker=ticker_n,
        analysis=analysis_d,
        execution_plan=plan_d,
        logged_intent=logged_order_intent,
        max_quote=max_quote,
    )
    if pending_ctx.get("intent_id") and not order_intent.get("intent_id"):
        order_intent["intent_id"] = pending_ctx.get("intent_id")

    risk = deepcopy(live_risk_result) if isinstance(live_risk_result, dict) else {}
    return _json_safe({
        "generated_at": _now_iso(),
        "source": "phase_c34_candidate_snapshot_extractor",
        "ticker": ticker_n,
        "fresh_analysis_id": _analysis_id(analysis_d) if analysis_d else None,
        "analysis": analysis_d,
        "execution_plan": plan_d,
        "order_intent": order_intent,
        "risk": risk,
        "live_risk_result": risk,
        "product_rules": _market_product_rules(analysis_d),
        "safety_policy": {
            "candidate_snapshot_is_not_execution_permission": True,
            "pending_intent_context_only": True,
            "deterministic_live_risk_must_be_real_not_fabricated": True,
            "no_coinbase_call_in_c34": True,
            "no_submit_in_c34": True,
        },
    })


def _source_status(name: str, value: Any, *, ticker: str) -> Dict[str, Any]:
    return {
        "name": name,
        "found": isinstance(value, dict) and bool(value),
        "ticker": _normalize_ticker((value or {}).get("ticker")) if isinstance(value, dict) else _normalize_ticker(ticker),
        "generated_at": (value or {}).get("generated_at") if isinstance(value, dict) else None,
    }


def build_phase_c34_candidate_snapshot_report(
    *,
    cfg: Any,
    ticker: str,
    analysis_log_path: str | Path = "logs/analysis.jsonl",
    execution_plan_log_path: str | Path = "logs/execution_plans.jsonl",
    pending_intents_path: str | Path = "state/pending_order_intents.json",
    order_events_path: str | Path = "logs/order_events.jsonl",
    paper_manager_path: str | Path = "logs/paper_order_manager.jsonl",
    pending_summary: Optional[Dict[str, Any]] = None,
    order_summary: Optional[Dict[str, Any]] = None,
    submit_audit_summary: Optional[Dict[str, Any]] = None,
    live_risk_result: Optional[Dict[str, Any]] = None,
    max_quote: Any = "10.00",
    max_lines: int = 2000,
) -> Dict[str, Any]:
    """Extract a candidate snapshot and immediately run it through C.3.3.

    C.3.4 is read-only: it reads logs/state and returns/writes JSON only when a
    caller explicitly does so. It never calls Coinbase, never changes .env and
    never submits orders.
    """
    ticker_n = _normalize_ticker(ticker)
    analysis = _latest_jsonl_for_ticker(analysis_log_path, ticker_n, max_lines=max_lines)
    execution_plan = _latest_jsonl_for_ticker(execution_plan_log_path, ticker_n, max_lines=max_lines)
    pending_intent = _latest_pending_intent_for_ticker(pending_intents_path, ticker_n)
    logged_order_intent = _latest_order_intent_for_ticker(
        ticker=ticker_n,
        order_events_path=order_events_path,
        paper_manager_path=paper_manager_path,
        max_lines=max_lines,
    )

    candidate = build_phase_c34_candidate_from_sources(
        ticker=ticker_n,
        analysis=analysis,
        execution_plan=execution_plan,
        pending_intent=pending_intent,
        logged_order_intent=logged_order_intent,
        live_risk_result=live_risk_result,
        max_quote=max_quote,
    ) if ticker_n else None

    c33_report = build_phase_c33_final_preflight_report(
        cfg=cfg,
        ticker=ticker_n,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit_summary,
        candidate=candidate,
        max_quote=max_quote,
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
    require(isinstance(analysis, dict), "latest_analysis_found", "latest_analysis_not_found")
    require(isinstance(execution_plan, dict), "latest_execution_plan_found", "latest_execution_plan_not_found")
    require(isinstance(pending_intent, dict), "pending_intent_found", "pending_intent_not_found")
    if isinstance(pending_intent, dict) and _intent_is_promotion_ready(pending_intent):
        passed.append("pending_intent_promotion_ready")
    elif isinstance(pending_intent, dict):
        blockers.append("pending_intent_not_promotion_ready")

    if isinstance(live_risk_result, dict) and live_risk_result:
        passed.append("live_risk_result_supplied")
    else:
        blockers.append("live_risk_result_not_supplied_or_not_found")
        warnings.append("C.3.4 does not fabricate live risk approval; C.3.3 must remain blocked until real deterministic risk is supplied")

    if isinstance(logged_order_intent, dict):
        passed.append("logged_actionable_order_intent_found")
    else:
        warnings.append("no_actionable_logged_paper_order_intent_found; derived intent may remain incomplete")

    extraction_ready = not blockers
    final_preflight_ready = bool(c33_report.get("final_preflight_snapshot_ready"))
    status = "candidate_snapshot_extracted_final_preflight_ready_no_submit" if final_preflight_ready else "candidate_snapshot_extracted_but_blocked"
    if not extraction_ready and not isinstance(candidate, dict):
        status = "blocked"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C3.4_candidate_snapshot_generator_extractor",
        "status": status,
        "ticker": ticker_n,
        "candidate_snapshot_extracted": isinstance(candidate, dict),
        "candidate_snapshot_structural_extraction_ready": extraction_ready,
        "final_preflight_snapshot_ready": final_preflight_ready,
        "ready_for_human_final_pilot_run_review": bool(c33_report.get("ready_for_human_final_pilot_run_review")),
        "actual_coinbase_submit_currently_enabled": bool(c33_report.get("actual_coinbase_submit_currently_enabled")),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "sources": {
            "analysis": _source_status("analysis", analysis, ticker=ticker_n),
            "execution_plan": _source_status("execution_plan", execution_plan, ticker=ticker_n),
            "pending_intent": _source_status("pending_intent", pending_intent, ticker=ticker_n),
            "logged_order_intent": _source_status("logged_order_intent", logged_order_intent, ticker=ticker_n),
        },
        "candidate": candidate,
        "c33_report": c33_report,
        "candidate_file_payload": {
            "ticker": ticker_n,
            "candidate": candidate,
            "c34_generated_at": _now_iso(),
            "safety_policy": {
                "candidate_file_is_not_execution_permission": True,
                "still_requires_c33_c34_green_and_human_go_no_go": True,
                "actual_submit_must_remain_false": True,
            },
        },
        "write_guidance": {
            "default_tool_mode": "report_only_no_write",
            "safe_output_dir": "state/phase_c_candidates",
            "c33_verify_command_template": f"python3 tools/show_phase_c33_candidate_preflight.py --ticker {ticker_n} --candidate-json <candidate-file> --json",
        },
        "safety_policy": {
            "c34_is_read_only_extractor": True,
            "does_not_modify_env": True,
            "does_not_call_coinbase": True,
            "does_not_submit": True,
            "does_not_fabricate_live_risk": True,
            "candidate_snapshot_is_not_execution_permission": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "build_phase_c34_candidate_from_sources",
    "build_phase_c34_candidate_snapshot_report",
]
