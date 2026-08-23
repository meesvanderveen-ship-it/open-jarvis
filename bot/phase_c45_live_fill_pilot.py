from __future__ import annotations

from copy import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.order_store import OrderStore
from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report
from bot.phase_c44_poll_to_apply_closeout import build_phase_c44_poll_to_apply_closeout_report
from bot.state_store import StateStore

C45_FILL_PILOT_PHASE = "C4.5_controlled_live_fill_pilot"
C45_FILL_APPLY_ACK = "I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY"
FILL_ACTIONS = {"fill_to_position", "record_partial_fill"}
FINAL_NON_FILL_ACTIONS = {"mark_cancelled", "mark_expired", "mark_rejected"}
OPEN_ACTIONS = {"kept_open", "no_live_snapshot"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _is_c43_open_entry_order(order: Dict[str, Any]) -> bool:
    return (
        str(order.get("side") or "").upper() == "BUY"
        and str(order.get("status") or "").lower() in {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"}
        and str(order.get("mode") or "").lower() == "live"
        and str(order.get("execution_action") or "").lower() == "place_limit_buy"
        and (order.get("opened_via_phase_c43") or str(order.get("source_mode") or "").lower() == "autonomous_small_live")
    )


def _clone_cfg_with_runtime_flags(
    cfg: Any,
    *,
    allow_coinbase_poll: bool,
    apply_local: bool,
    build_d2_plan: bool,
    persist_d2_plan: bool,
    build_d3_preview: bool,
) -> Any:
    cloned = copy(cfg)
    setattr(cloned, "enable_phase_c43_lifecycle_orchestrator", True)
    setattr(cloned, "phase_c43_lifecycle_allow_coinbase_poll", bool(allow_coinbase_poll))
    setattr(cloned, "phase_c43_lifecycle_apply_local", bool(apply_local))
    setattr(cloned, "phase_c43_lifecycle_build_d2_plan", bool(build_d2_plan))
    setattr(cloned, "phase_c43_lifecycle_persist_d2_plan", bool(persist_d2_plan))
    setattr(cloned, "phase_c43_lifecycle_build_d3_preview", bool(build_d3_preview))
    return cloned


def _action_names(c44_report: Dict[str, Any]) -> set[str]:
    preview = c44_report.get("preview_report") or {}
    return {str(a.get("action") or "unknown") for a in (preview.get("proposed_actions") or [])}


def _applied_actions(c44_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    apply = c44_report.get("apply_report") or {}
    actions = apply.get("applied_actions") or []
    return [a for a in actions if isinstance(a, dict)]


def _summarize_fill_apply(c44_report: Dict[str, Any]) -> Dict[str, Any]:
    applied = _applied_actions(c44_report)
    fill_applied = [a for a in applied if str(a.get("action") or a.get("source") or "") in {"filled_to_position", "fill_to_position", "record_partial_fill", "c43_fill_reconciler"}]
    return {
        "applied_actions_count": len(applied),
        "fill_related_applied_actions_count": len(fill_applied),
        "position_created": any(bool(a.get("position")) or bool(a.get("position_created")) for a in applied),
        "d2_reports_count": len(((c44_report.get("apply_report") or {}).get("d2_reports") or [])),
        "d3_previews_count": len(((c44_report.get("apply_report") or {}).get("d3_previews") or [])),
    }


def _derive_status(*, blockers: List[str], action_names: set[str], apply_fill: bool, c44_report: Dict[str, Any]) -> str:
    if blockers:
        return "blocked_review_required"
    if not action_names:
        return "no_open_c43_order_noop"
    if action_names <= OPEN_ACTIONS:
        return "fill_pilot_waiting_for_fill"
    if action_names & FINAL_NON_FILL_ACTIONS:
        return "non_fill_closeout_detected_use_c44"
    if action_names & FILL_ACTIONS and not apply_fill:
        return "fill_detected_review_required"
    if apply_fill and c44_report.get("status") == "closeout_apply_local_completed":
        return "fill_apply_local_completed"
    if apply_fill:
        return "fill_apply_review_required"
    return "fill_pilot_preview_ready"


def build_phase_c45_live_fill_pilot_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    apply_fill: bool = False,
    fill_apply_ack: str = "",
    build_d2_plan: bool = False,
    persist_d2_plan: bool = False,
    build_d3_preview: bool = False,
) -> Dict[str, Any]:
    """Controlled C.4.5 fill pilot for an existing C.4.3 live BUY order.

    This layer intentionally does not place a new order. It is the bridge between
    the live entry/closeout workflow and product fill handling: poll/preview an
    already-open C.4.3 order, require explicit fill apply authorization when a
    fill/partial-fill is observed, then delegate to C.4.4.4/C.4.3 lifecycle logic
    for local fill-to-position, optional D.2 planning and D.3 preview.

    Safety invariants: no Coinbase submit/cancel/replace and no live SELL.
    """
    selected = _normalize_ticker(ticker)
    store = order_store or OrderStore(
        path=getattr(cfg, "phase_c43_lifecycle_order_store_path", "state/open_orders.json"),
        log_path=getattr(cfg, "phase_c43_lifecycle_order_events_path", "logs/order_events.jsonl"),
        max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))),
    )
    state = state_store or StateStore()
    open_orders = [o for o in store.open_entry_orders(ticker=selected or None) if _is_c43_open_entry_order(o)]

    blockers: List[str] = []
    warnings: List[str] = []
    passed_checks: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed_checks.append(ok)
        else:
            blockers.append(bad)

    require(not _cfg_bool(cfg, "replication_enabled", False), "replication_disabled", "replication_enabled_review_required")
    require(not _cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False), "entry_actual_submit_disabled", "entry_actual_submit_still_enabled")
    require(not _cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(not _cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_exits_disabled", "autonomous_allow_exits_enabled_forbidden")
    require(not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False), "d3_actual_exit_submit_disabled", "d3_actual_exit_submit_enabled_forbidden")
    require(len(open_orders) <= 1, "max_one_open_c43_order_for_fill_pilot", "multiple_open_c43_orders_block_fill_pilot")

    if not open_orders:
        warnings.append("no_open_c43_order_for_fill_pilot")
    if apply_fill:
        require(fill_apply_ack == C45_FILL_APPLY_ACK, "c45_fill_apply_ack_ok", "c45_fill_apply_ack_missing_or_wrong")
    if (build_d2_plan or build_d3_preview or persist_d2_plan) and not apply_fill:
        blockers.append("d2_d3_requested_without_apply_fill")
    if build_d3_preview and _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False):
        blockers.append("d3_preview_blocked_because_actual_exit_submit_enabled")

    requested_cfg = _clone_cfg_with_runtime_flags(
        cfg,
        allow_coinbase_poll=allow_coinbase_poll or bool(live_orders_snapshot),
        apply_local=apply_fill,
        build_d2_plan=build_d2_plan,
        persist_d2_plan=persist_d2_plan,
        build_d3_preview=build_d3_preview,
    )
    governance = build_phase_c43_lifecycle_governance_report(
        cfg=requested_cfg,
        local_open_c43_orders=open_orders,
        ticker=selected or "ALL",
        cycle_type="c45_live_fill_pilot",
        source="phase_c45_live_fill_pilot",
    )
    if governance.get("blockers"):
        blockers.append("lifecycle_governance_has_blockers")

    # Even when apply_fill is requested, the underlying C.4.4.4 wrapper previews
    # first and only applies after governed fill evidence plus explicit ACK.
    c44_report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=cfg,
        ticker=selected or "ALL",
        order_store=store,
        state_store=state,
        coinbase_client=coinbase_client,
        live_orders_snapshot=live_orders_snapshot,
        allow_coinbase_poll=allow_coinbase_poll,
        apply_local=bool(apply_fill and not blockers),
        allow_fill_apply=bool(apply_fill and not blockers),
        build_d2_plan=bool(build_d2_plan and not blockers),
        persist_d2_plan=bool(persist_d2_plan and not blockers),
        build_d3_preview=bool(build_d3_preview and not blockers),
    )

    actions = _action_names(c44_report)
    if actions & FINAL_NON_FILL_ACTIONS:
        warnings.append("non_fill_final_status_detected_use_c44_closeout_route")
    if actions & FILL_ACTIONS and not apply_fill:
        blockers.append("fill_or_partial_fill_detected_requires_c45_apply_fill_ack")

    final_open = [o for o in store.open_entry_orders(ticker=selected or None) if _is_c43_open_entry_order(o)]
    status = _derive_status(blockers=blockers, action_names=actions, apply_fill=apply_fill, c44_report=c44_report)

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C45_FILL_PILOT_PHASE,
        "status": status,
        "ticker": selected or "ALL",
        "requested": {
            "allow_coinbase_poll": bool(allow_coinbase_poll),
            "apply_fill": bool(apply_fill),
            "build_d2_plan": bool(build_d2_plan),
            "persist_d2_plan": bool(persist_d2_plan),
            "build_d3_preview": bool(build_d3_preview),
            "using_provided_snapshots": bool(live_orders_snapshot),
        },
        "local_open_c43_before": len(open_orders),
        "local_open_c43_after": len(final_open),
        "governance_report": governance,
        "c44_report": c44_report,
        "fill_apply_summary": _summarize_fill_apply(c44_report),
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed_checks,
        "safety_policy": {
            "does_not_place_entry_orders": True,
            "never_submits_to_coinbase": True,
            "never_cancels_on_coinbase": True,
            "never_replaces_on_coinbase": True,
            "never_submits_live_sell_orders": True,
            "coinbase_poll_is_read_only": True,
            "preview_before_apply": True,
            "fill_apply_requires_explicit_c45_ack": True,
            "positions_opened_only_after_fill_evidence": True,
            "d3_preview_forces_submit_live_false": True,
        },
        "next_step": "Bij OPEN: wachten of handmatig cancelen via C.4.4.4. Bij FILLED/PARTIAL: opnieuw draaien met --apply-fill, exacte ACK, --build-d2-plan en --build-d3-preview. Live SELL blijft uit.",
    })


__all__ = [
    "C45_FILL_PILOT_PHASE",
    "C45_FILL_APPLY_ACK",
    "build_phase_c45_live_fill_pilot_report",
]
