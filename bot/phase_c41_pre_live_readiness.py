from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bot.phase_c37_candidate_promotion_hardening import (
    build_phase_c37_candidate_promotion_hardening_report,
    summarize_phase_c37_live_risk_bridge,
)
from bot.phase_c38_final_pilot_executor_scaffold import build_phase_c38_final_pilot_executor_report
from bot.phase_c40_live_order_safety_layer import build_phase_c40_live_order_safety_report

ZERO = Decimal("0")
C41_MAX_QUOTE_CAP = Decimal("10.00")
C41_EMERGENCY_CANCEL_ACK = "I_UNDERSTAND_AND_APPROVE_PHASE_C41_EMERGENCY_CANCEL_ONLY"
C41_EMERGENCY_CANCEL_MODE = "emergency_cancel_live"


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
        return json.loads(Path(path).read_text(encoding="utf-8"))
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


def _extract_payload_from_c38(c38_report: Dict[str, Any]) -> Dict[str, Any]:
    return _as_dict(c38_report.get("payload_preview_summary"))


def _extract_quote(payload: Dict[str, Any]) -> Decimal:
    return _to_decimal(payload.get("size_quote_normalized") or payload.get("size_quote_requested"), "0")


def assess_phase_c41_pre_live_readiness(
    *,
    cfg: Any,
    ticker: str,
    c37_report: Dict[str, Any],
    c38_report: Dict[str, Any],
    c40_report: Dict[str, Any],
    live_risk_bridge: Dict[str, Any],
    require_controlled_coinbase_poll: bool = True,
    max_quote: Decimal | str = C41_MAX_QUOTE_CAP,
) -> Dict[str, Any]:
    """Assess final pre-live readiness without enabling submit or cancel.

    C.4.1 is the combined pre-live checklist layer. It requires the candidate side,
    risk side and order-safety side to be green, while final live hardlocks stay off.
    """
    selected = _normalize_ticker(ticker)
    max_quote_d = _to_decimal(max_quote, str(C41_MAX_QUOTE_CAP))
    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    actual_submit = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    live_exits = bool(getattr(cfg, "enable_live_exit_orders", False))
    if actual_submit:
        blockers.append("actual_coinbase_submit_enabled_before_final_live_window")
    else:
        passed.append("actual_coinbase_submit_disabled")
    if live_exits:
        blockers.append("live_exit_orders_enabled_forbidden_pre_live")
    else:
        passed.append("live_exit_orders_disabled")

    c37_actionable = selected in _as_list(c37_report.get("actionable_preflight_ready_tickers"))
    c37_status = str(c37_report.get("status") or "")
    if c37_actionable:
        passed.append("c37_selected_ticker_actionable")
    else:
        blockers.append("c37_selected_ticker_not_actionable")

    candidate = _as_dict(c37_report.get("selected_candidate_assessment"))
    if bool(candidate.get("actionable_for_future_pilot_review")):
        passed.append("c37_selected_candidate_assessment_actionable")
    else:
        blockers.append("c37_selected_candidate_assessment_not_actionable")

    c38_hardlock = _as_dict(c38_report.get("hardlock_assessment"))
    readiness_locks = _as_dict(c38_hardlock.get("readiness_locks"))
    payload = _extract_payload_from_c38(c38_report)
    quote = _extract_quote(payload)
    payload_accepted = bool(payload.get("accepted"))
    side_buy = str(payload.get("side") or "").upper() == "BUY"
    post_only = bool(payload.get("post_only"))

    if bool(readiness_locks.get("c37_candidate_actionable")):
        passed.append("c38_readiness_c37_candidate_actionable")
    else:
        blockers.append("c38_readiness_c37_candidate_not_actionable")
    if bool(readiness_locks.get("c36_dry_run_ready_no_submit")):
        passed.append("c38_readiness_c36_dry_run_ready")
    else:
        blockers.append("c38_readiness_c36_dry_run_not_ready")
    if payload_accepted:
        passed.append("payload_accepted")
    else:
        blockers.append("payload_not_accepted")
    if side_buy:
        passed.append("payload_side_buy")
    else:
        blockers.append("payload_side_not_buy")
    if post_only:
        passed.append("payload_post_only")
    else:
        blockers.append("payload_not_post_only")
    if quote > ZERO and quote <= max_quote_d:
        passed.append("payload_quote_within_pre_live_cap")
    else:
        blockers.append("payload_quote_missing_or_above_cap")

    accepted_risk = selected in _as_list(live_risk_bridge.get("accepted_live_risk_tickers"))
    if accepted_risk:
        passed.append("deterministic_live_risk_accepted_for_selected_ticker")
    else:
        blockers.append("deterministic_live_risk_missing_or_not_accepted")

    c40_safety = _as_dict(c40_report.get("safety_assessment"))
    c40_counts = _as_dict(c40_safety.get("counts"))
    coinbase_poll = _as_dict(c40_report.get("coinbase_poll"))
    poll_attempted = bool(coinbase_poll.get("coinbase_call_attempted"))
    poll_succeeded = bool(coinbase_poll.get("coinbase_call_succeeded"))
    if require_controlled_coinbase_poll:
        if poll_attempted and poll_succeeded:
            passed.append("controlled_coinbase_open_order_poll_succeeded")
        else:
            blockers.append("controlled_coinbase_open_order_poll_not_succeeded")
    else:
        warnings.append("controlled_coinbase_poll_not_required_for_this_report")

    if int(c40_counts.get("live_unmanaged_orders") or 0) == 0:
        passed.append("no_unmanaged_live_orders")
    else:
        blockers.append("unmanaged_live_open_orders_detected")
    if int(c40_counts.get("live_open_orders") or 0) <= 1:
        passed.append("max_one_live_open_order_or_none")
    else:
        blockers.append("too_many_live_open_orders_for_pilot")
    if int(c40_counts.get("partial_fill_like_orders") or 0) == 0:
        passed.append("no_partial_fill_like_orders_before_live")
    else:
        blockers.append("partial_fill_like_order_requires_reconciliation_before_live")
    if not _as_list(c40_safety.get("blockers")):
        passed.append("c40_order_safety_has_no_blockers")
    else:
        blockers.append("c40_order_safety_blocked")

    # Final live locks must still be off in this pre-live phase.
    if bool(c38_report.get("can_attempt_live_submit")):
        blockers.append("c38_can_attempt_live_submit_unexpected_in_pre_live")
    else:
        passed.append("c38_final_live_submit_hardlocked")
    if bool(c38_report.get("live_submission_attempted_by_this_tool")) or bool(c38_report.get("live_order_submitted")):
        blockers.append("c38_live_attempt_or_submit_detected")
    else:
        passed.append("c38_no_live_attempt_or_submit")
    if bool(c40_report.get("dry_run_cancel_plan", {}).get("cancel_attempted_by_this_tool")) or bool(c40_report.get("dry_run_cancel_plan", {}).get("cancel_submitted")):
        blockers.append("c40_cancel_attempt_or_submit_detected")
    else:
        passed.append("c40_no_cancel_attempt_or_submit")

    # De-duplicate preserving order.
    blockers = list(dict.fromkeys([b for b in blockers if b]))
    warnings = list(dict.fromkeys([w for w in warnings if w]))
    passed = list(dict.fromkeys([p for p in passed if p]))
    ready = not blockers
    return _json_safe({
        "pre_live_ready_no_submit": ready,
        "status": "pre_live_ready_no_submit" if ready else "pre_live_readiness_blocked",
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "readiness_summary": {
            "ticker": selected,
            "c37_status": c37_status,
            "c37_actionable": c37_actionable,
            "payload_accepted": payload_accepted,
            "payload_side_buy": side_buy,
            "payload_post_only": post_only,
            "payload_quote": str(quote),
            "payload_quote_cap": str(max_quote_d),
            "deterministic_live_risk_accepted": accepted_risk,
            "controlled_coinbase_poll_attempted": poll_attempted,
            "controlled_coinbase_poll_succeeded": poll_succeeded,
            "live_open_orders": int(c40_counts.get("live_open_orders") or 0),
            "live_unmanaged_orders": int(c40_counts.get("live_unmanaged_orders") or 0),
            "partial_fill_like_orders": int(c40_counts.get("partial_fill_like_orders") or 0),
            "actual_submit_still_disabled": not actual_submit,
        },
        "safety_policy": {
            "pre_live_does_not_submit": True,
            "pre_live_does_not_cancel": True,
            "actual_submit_must_remain_false": True,
            "requires_actionable_c37_candidate": True,
            "requires_accepted_real_live_risk_snapshot": True,
            "requires_controlled_coinbase_open_order_poll": bool(require_controlled_coinbase_poll),
            "requires_no_unmanaged_live_orders": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


def _candidate_cancel_orders(c40_report: Dict[str, Any], explicit_order_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    explicit = [str(x).strip() for x in (explicit_order_ids or []) if str(x).strip()]
    out: List[Dict[str, Any]] = []
    live_orders = _as_list(c40_report.get("live_orders"))
    if explicit:
        ids = set(explicit)
        for order in live_orders:
            od = _as_dict(order)
            oid = str(od.get("order_id") or "").strip()
            cid = str(od.get("client_order_id") or "").strip()
            if oid in ids or cid in ids:
                out.append(od)
        # Include IDs even if no matching snapshot order is present, but keep them diagnostic.
        known = {str(o.get("order_id") or o.get("client_order_id") or "").strip() for o in out}
        for oid in ids - known:
            out.append({"order_id": oid, "client_order_id": None, "ticker": None, "source": "explicit_cancel_id_not_in_snapshot"})
        return out
    recs = _as_list(_as_dict(c40_report.get("dry_run_cancel_plan")).get("recommendations"))
    for rec in recs:
        rd = _as_dict(rec)
        out.append({
            "ticker": rd.get("ticker"),
            "client_order_id": rd.get("client_order_id"),
            "order_id": rd.get("order_id"),
            "source": "c40_cancel_recommendation",
            "reasons": rd.get("reasons") or [],
        })
    return out


def assess_phase_c41_emergency_cancel_hardlock(
    *,
    c40_report: Dict[str, Any],
    emergency_cancel_mode: str = "dry_run",
    human_cancel_ack: str = "",
    cancel_live: bool = False,
    coinbase_client: Any = None,
    cancel_order_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    orders = _candidate_cancel_orders(c40_report, explicit_order_ids=cancel_order_ids)
    blockers: List[str] = []
    passed: List[str] = []
    if emergency_cancel_mode == C41_EMERGENCY_CANCEL_MODE:
        passed.append("emergency_cancel_mode_final")
    else:
        blockers.append("emergency_cancel_mode_not_final")
    if human_cancel_ack == C41_EMERGENCY_CANCEL_ACK:
        passed.append("human_emergency_cancel_ack_ok")
    else:
        blockers.append("human_emergency_cancel_ack_missing_or_wrong")
    if bool(cancel_live):
        passed.append("cancel_live_argument_true")
    else:
        blockers.append("cancel_live_argument_false")
    if coinbase_client is not None:
        passed.append("coinbase_client_provided")
    else:
        blockers.append("coinbase_client_not_provided")
    if orders:
        passed.append("cancel_order_candidates_present")
    else:
        blockers.append("no_cancel_order_candidates")
    if not (hasattr(coinbase_client, "cancel_order") or hasattr(coinbase_client, "cancel_orders")):
        blockers.append("coinbase_client_has_no_supported_cancel_method")
    else:
        passed.append("coinbase_client_has_supported_cancel_method")
    can_cancel = not blockers
    return _json_safe({
        "can_attempt_emergency_cancel": can_cancel,
        "blockers": list(dict.fromkeys(blockers)),
        "passed_checks": list(dict.fromkeys(passed)),
        "cancel_order_candidates": orders,
        "live_cancel_hardlocks": {
            "emergency_cancel_mode_required": C41_EMERGENCY_CANCEL_MODE,
            "emergency_cancel_mode_provided": emergency_cancel_mode,
            "human_cancel_ack_required": C41_EMERGENCY_CANCEL_ACK,
            "human_cancel_ack_ok": human_cancel_ack == C41_EMERGENCY_CANCEL_ACK,
            "cancel_live_argument": bool(cancel_live),
            "coinbase_client_provided": coinbase_client is not None,
        },
        "safety_policy": {
            "default_does_not_cancel": True,
            "requires_explicit_cancel_live_true": True,
            "requires_exact_human_cancel_ack": True,
            "requires_coinbase_client": True,
            "cancel_is_emergency_only": True,
        },
    })


def maybe_execute_phase_c41_emergency_cancel(
    *,
    c40_report: Dict[str, Any],
    emergency_cancel_mode: str = "dry_run",
    human_cancel_ack: str = "",
    cancel_live: bool = False,
    coinbase_client: Any = None,
    cancel_order_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    hardlock = assess_phase_c41_emergency_cancel_hardlock(
        c40_report=c40_report,
        emergency_cancel_mode=emergency_cancel_mode,
        human_cancel_ack=human_cancel_ack,
        cancel_live=cancel_live,
        coinbase_client=coinbase_client,
        cancel_order_ids=cancel_order_ids,
    )
    if not hardlock["can_attempt_emergency_cancel"]:
        return _json_safe({
            "status": "emergency_cancel_not_attempted_hardlocked",
            "cancel_attempted_by_this_tool": False,
            "cancel_submitted": False,
            "hardlock": hardlock,
            "results": [],
        })
    results: List[Dict[str, Any]] = []
    for order in hardlock.get("cancel_order_candidates", []):
        od = _as_dict(order)
        order_id = str(od.get("order_id") or od.get("client_order_id") or "").strip()
        if not order_id:
            results.append({"status": "skipped_missing_order_id", "order": od})
            continue
        try:
            if hasattr(coinbase_client, "cancel_order"):
                res = coinbase_client.cancel_order(order_id=order_id)
            else:
                res = coinbase_client.cancel_orders(order_ids=[order_id])
            results.append({"status": "cancel_submitted", "order_id": order_id, "response": res})
        except Exception as exc:
            results.append({"status": "cancel_error", "order_id": order_id, "error": str(exc)})
    submitted = any(r.get("status") == "cancel_submitted" for r in results)
    return _json_safe({
        "status": "emergency_cancel_submitted" if submitted else "emergency_cancel_attempted_no_submit",
        "cancel_attempted_by_this_tool": True,
        "cancel_submitted": submitted,
        "hardlock": hardlock,
        "results": results,
    })


def build_phase_c41_pre_live_readiness_report(
    *,
    cfg: Any,
    ticker: Optional[str] = None,
    live_orders_snapshot: Optional[Sequence[Dict[str, Any]]] = None,
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    live_risk_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    risk_dir: str | Path | None = None,
    order_store_path: str | Path = "state/open_orders.json",
    order_events_path: str | Path = "logs/order_events.jsonl",
    c37_report: Optional[Dict[str, Any]] = None,
    c38_report: Optional[Dict[str, Any]] = None,
    c40_report: Optional[Dict[str, Any]] = None,
    require_controlled_coinbase_poll: bool = True,
    emergency_cancel_mode: str = "dry_run",
    human_cancel_ack: str = "",
    cancel_live: bool = False,
    cancel_order_ids: Optional[Sequence[str]] = None,
    cancel_coinbase_client: Any = None,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker) or "BTC-USDC"
    risk_map = _normalize_risk_map(live_risk_by_ticker, risk_dir)
    risk_bridge = summarize_phase_c37_live_risk_bridge(live_risk_by_ticker=risk_map)
    c37 = c37_report or build_phase_c37_candidate_promotion_hardening_report(
        cfg=cfg,
        ticker=selected,
        live_risk_by_ticker=risk_map,
    )
    c38 = c38_report or build_phase_c38_final_pilot_executor_report(
        cfg=cfg,
        ticker=selected,
        c37_report=c37,
    )
    c40 = c40_report or build_phase_c40_live_order_safety_report(
        cfg=cfg,
        ticker=selected,
        live_orders_snapshot=live_orders_snapshot,
        coinbase_client=coinbase_client,
        allow_coinbase_poll=allow_coinbase_poll,
        order_store_path=order_store_path,
        order_events_path=order_events_path,
    )
    readiness = assess_phase_c41_pre_live_readiness(
        cfg=cfg,
        ticker=selected,
        c37_report=c37,
        c38_report=c38,
        c40_report=c40,
        live_risk_bridge=risk_bridge,
        require_controlled_coinbase_poll=require_controlled_coinbase_poll,
    )
    cancel_result = maybe_execute_phase_c41_emergency_cancel(
        c40_report=c40,
        emergency_cancel_mode=emergency_cancel_mode,
        human_cancel_ack=human_cancel_ack,
        cancel_live=cancel_live,
        coinbase_client=cancel_coinbase_client,
        cancel_order_ids=cancel_order_ids,
    )
    status = readiness.get("status")
    if cancel_result.get("cancel_submitted"):
        status = "pre_live_emergency_cancel_submitted"
    elif cancel_result.get("cancel_attempted_by_this_tool"):
        status = "pre_live_emergency_cancel_attempted_review"
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C4.1_combined_pre_live_readiness_poll_risk_cancel_hardlock",
        "status": status,
        "config_ok": True,
        "selected_ticker": selected,
        "pre_live_ready_no_submit": bool(readiness.get("pre_live_ready_no_submit")),
        "actual_coinbase_submit_currently_enabled": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "cancel_attempted_by_this_tool": bool(cancel_result.get("cancel_attempted_by_this_tool")),
        "cancel_submitted": bool(cancel_result.get("cancel_submitted")),
        "readiness": readiness,
        "live_risk_bridge": risk_bridge,
        "c37_summary": {
            "status": c37.get("status"),
            "actionable_preflight_ready_tickers": c37.get("actionable_preflight_ready_tickers") or [],
            "blocked_or_context_tickers": c37.get("blocked_or_context_tickers") or [],
            "counts": c37.get("counts") or {},
        },
        "c38_summary": {
            "status": c38.get("status"),
            "can_attempt_live_submit": bool(c38.get("can_attempt_live_submit")),
            "hardlock_blockers": _as_dict(c38.get("hardlock_assessment")).get("blockers") or [],
            "payload_preview_summary": c38.get("payload_preview_summary") or {},
        },
        "c40_summary": {
            "status": c40.get("status"),
            "coinbase_poll": c40.get("coinbase_poll") or {},
            "counts": _as_dict(c40.get("safety_assessment")).get("counts") or {},
            "blockers": _as_dict(c40.get("safety_assessment")).get("blockers") or [],
            "warnings": _as_dict(c40.get("safety_assessment")).get("warnings") or [],
            "recommendations": _as_dict(c40.get("safety_assessment")).get("recommendations") or [],
        },
        "emergency_cancel": cancel_result,
        "final_pre_live_checklist": [
            "C.3.7 moet precies één actionable_preflight_ready ticker tonen voor de gekozen pilot.",
            "C.3.8 moet nog hardlocked zijn, maar readiness locks voor BUY/payload/post-only/quote moeten groen zijn.",
            "Deterministic live-risk snapshot moet live accepted zijn voor dezelfde ticker; C.4.1 verzint dit nooit.",
            "Controlled Coinbase open-order poll moet geslaagd zijn en 0 unmanaged orders tonen.",
            "Emergency cancel hardlock moet beschikbaar zijn maar niet geactiveerd in de normale pre-live check.",
            "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT blijft false tot het expliciete finale live venster.",
            "Live exits blijven false; followers blijven buiten order-lifecycle.",
            "Na eventuele latere live poging: direct rollback naar actual submit false, service herstarten, C.4.1 opnieuw draaien.",
        ],
        "rollback_commands": [
            "python3 - <<'PY'\nfrom pathlib import Path\nimport re\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\nif re.search(r'^PHASE_C_ALLOWED_TICKERS=.*$', s, re.M):\n    s=re.sub(r'^PHASE_C_ALLOWED_TICKERS=.*$', 'PHASE_C_ALLOWED_TICKERS=', s, flags=re.M)\np.write_text(s)\nPY",
            "sudo systemctl restart coinbase-bot",
            "python3 tools/show_phase_c41_pre_live_readiness.py --ticker BTC-USDC --json",
            "python3 tools/show_phase_c40_live_order_safety.py --ticker BTC-USDC --json",
            "python3 tools/show_phase_c_submit_readiness.py --json",
        ],
        "safety_policy": {
            "c41_combines_all_pre_live_checks": True,
            "does_not_submit": True,
            "does_not_modify_env": True,
            "default_does_not_cancel": True,
            "actual_submit_must_remain_false": True,
            "controlled_coinbase_poll_requires_explicit_allow_and_client": True,
            "emergency_cancel_requires_separate_hardlocks": True,
            "does_not_fabricate_live_risk": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "C41_EMERGENCY_CANCEL_ACK",
    "C41_EMERGENCY_CANCEL_MODE",
    "assess_phase_c41_pre_live_readiness",
    "assess_phase_c41_emergency_cancel_hardlock",
    "maybe_execute_phase_c41_emergency_cancel",
    "build_phase_c41_pre_live_readiness_report",
]
