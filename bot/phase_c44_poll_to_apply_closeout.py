from __future__ import annotations

import json
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.order_store import OrderStore
from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report
from bot.phase_c43_lifecycle_orchestrator import build_phase_c43_lifecycle_orchestrator_report
from bot.state_store import StateStore

C44_CLOSEOUT_PHASE = "C4.4.4_poll_to_apply_closeout"
FINAL_NON_FILL_ACTIONS = {"mark_cancelled", "mark_expired", "mark_rejected"}
FILL_ACTIONS = {"fill_to_position", "record_partial_fill"}
SAFE_PREVIEW_ACTIONS = {"kept_open", "no_live_snapshot"} | FINAL_NON_FILL_ACTIONS | FILL_ACTIONS


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
    return str(value or "").strip().upper()


def _cfg_with_runtime_flags(
    cfg: Any,
    *,
    request_coinbase_poll: bool,
    request_apply_local: bool,
    request_build_d2_plan: bool = False,
    request_persist_d2_plan: bool = False,
    request_build_d3_preview: bool = False,
) -> Any:
    """Return a shallow config proxy with explicit C.4.4.4 runtime lifecycle flags.

    The user may run this tool without editing .env. Governance still sees the
    requested flags and decides the effective behavior. Non-lifecycle safety
    flags (live exits, replication, D3 actual submit) are inherited unchanged.
    """
    proxy = copy(cfg)
    setattr(proxy, "enable_phase_c43_lifecycle_orchestrator", True)
    setattr(proxy, "phase_c43_lifecycle_allow_coinbase_poll", bool(request_coinbase_poll))
    setattr(proxy, "phase_c43_lifecycle_apply_local", bool(request_apply_local))
    setattr(proxy, "phase_c43_lifecycle_build_d2_plan", bool(request_build_d2_plan))
    setattr(proxy, "phase_c43_lifecycle_persist_d2_plan", bool(request_persist_d2_plan))
    setattr(proxy, "phase_c43_lifecycle_build_d3_preview", bool(request_build_d3_preview))
    return proxy


def _is_c43_open_entry_order(order: Dict[str, Any]) -> bool:
    return (
        str(order.get("side") or "").upper() == "BUY"
        and str(order.get("status") or "").lower() in {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"}
        and str(order.get("mode") or "").lower() == "live"
        and str(order.get("execution_action") or "").lower() == "place_limit_buy"
        and (order.get("opened_via_phase_c43") or str(order.get("source_mode") or "").lower() == "autonomous_small_live")
    )


def _load_snapshot_file(path: Optional[str | Path]) -> Optional[List[Dict[str, Any]]]:
    if not path:
        return None
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if isinstance(data.get("snapshots"), list):
            return [x for x in data["snapshots"] if isinstance(x, dict)]
        if isinstance(data.get("orders"), list):
            return [x for x in data["orders"] if isinstance(x, dict)]
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    raise ValueError("snapshot file must contain a dict, list, or {'snapshots': [...]} payload")


def _action_summary(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_action: Dict[str, int] = {}
    actionable = 0
    final_non_fill = 0
    fill_related = 0
    for action in actions:
        key = str(action.get("action") or "unknown")
        by_action[key] = by_action.get(key, 0) + 1
        if bool(action.get("writes_local_state")):
            actionable += 1
        if key in FINAL_NON_FILL_ACTIONS:
            final_non_fill += 1
        if key in FILL_ACTIONS:
            fill_related += 1
    return {
        "total": len(actions),
        "by_action": by_action,
        "actionable_writes": actionable,
        "final_non_fill_closeouts": final_non_fill,
        "fill_related_actions": fill_related,
    }



def _extract_snapshots_from_preview_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return normalized read-only snapshots embedded in preview actions.

    C.4.4.4 always previews first. When apply-local is requested, using the
    already-previewed snapshots avoids the failure mode where the apply pass is
    invoked without Coinbase polling/snapshots and therefore turns a real
    mark_cancelled action into no_live_snapshot.
    """
    snapshots: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        snap = action.get("snapshot")
        if not isinstance(snap, dict):
            continue
        key = str(
            snap.get("client_order_id")
            or snap.get("exchange_order_id")
            or snap.get("order_id")
            or action.get("client_order_id")
            or action.get("exchange_order_id")
            or len(snapshots)
        )
        if key in seen:
            continue
        seen.add(key)
        snapshots.append(snap)
    return snapshots


def _derive_closeout_status(
    *,
    governance: Dict[str, Any],
    preview_report: Dict[str, Any],
    apply_report: Optional[Dict[str, Any]],
    request_apply_local: bool,
    allow_fill_apply: bool,
    blockers: List[str],
) -> str:
    if blockers:
        return "blocked_review_required"
    actions = preview_report.get("proposed_actions") or []
    if not actions:
        return "no_open_c43_orders_noop"
    action_names = {str(a.get("action") or "unknown") for a in actions}
    if action_names <= {"kept_open"}:
        return "open_order_kept_open_no_apply_needed"
    if action_names <= {"no_live_snapshot"}:
        return "no_live_snapshot_preview_only"
    if not request_apply_local:
        return "closeout_preview_ready"
    if apply_report is not None:
        if apply_report.get("applied_actions"):
            return "closeout_apply_local_completed"
        if any(bool(a.get("writes_local_state")) for a in actions):
            return "apply_local_expected_actions_missing_review"
        return "apply_local_completed_no_actions"
    if governance.get("effective_flags", {}).get("apply_local") is not True:
        return "apply_local_requested_but_not_effective"
    if any(a in FILL_ACTIONS for a in action_names) and not allow_fill_apply:
        return "fill_detected_review_required"
    return "closeout_preview_ready"


def build_phase_c44_poll_to_apply_closeout_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    apply_local: bool = False,
    build_d2_plan: bool = False,
    persist_d2_plan: bool = False,
    build_d3_preview: bool = False,
    allow_fill_apply: bool = False,
) -> Dict[str, Any]:
    """Governed C.4.4.4 closeout runner.

    This is a workflow wrapper around C.4.4.2 governance and the existing
    lifecycle orchestrator. It is meant for real-order closeout troubleshooting:
    preview Coinbase/fake snapshots first, then apply local lifecycle changes
    only when governance makes apply_local effective.

    It never submits/cancels/replaces Coinbase orders and never submits live
    SELL orders. Coinbase polling, when enabled, is read-only.
    """
    selected = _normalize_ticker(ticker)
    store = order_store or OrderStore(path=getattr(cfg, "phase_c43_lifecycle_order_store_path", "state/open_orders.json"), log_path=getattr(cfg, "phase_c43_lifecycle_order_events_path", "logs/order_events.jsonl"), max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))))
    state = state_store or StateStore()
    open_orders = [o for o in store.open_entry_orders(ticker=selected or None) if _is_c43_open_entry_order(o)]

    requested_cfg = _cfg_with_runtime_flags(
        cfg,
        request_coinbase_poll=allow_coinbase_poll or bool(live_orders_snapshot),
        request_apply_local=apply_local,
        request_build_d2_plan=build_d2_plan,
        request_persist_d2_plan=persist_d2_plan,
        request_build_d3_preview=build_d3_preview,
    )
    governance = build_phase_c43_lifecycle_governance_report(
        cfg=requested_cfg,
        local_open_c43_orders=open_orders,
        ticker=selected or "ALL",
        cycle_type="c44_poll_to_apply_closeout",
        source="phase_c44_poll_to_apply_closeout",
    )
    effective = governance.get("effective_flags") or {}

    preview_report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=cfg,
        ticker=selected or "ALL",
        order_store=store,
        state_store=state,
        coinbase_client=coinbase_client if bool(effective.get("allow_coinbase_poll")) else None,
        live_orders_snapshot=live_orders_snapshot,
        allow_coinbase_poll=bool(effective.get("allow_coinbase_poll")) and coinbase_client is not None,
        apply_local=False,
        build_d2_plan=False,
        persist_d2_plan=False,
        build_d3_preview=False,
    )

    proposed_actions = preview_report.get("proposed_actions") or []
    action_names = {str(a.get("action") or "unknown") for a in proposed_actions}
    blockers: List[str] = []
    warnings: List[str] = []

    unexpected = sorted(a for a in action_names if a not in SAFE_PREVIEW_ACTIONS)
    if unexpected:
        blockers.append("unexpected_lifecycle_actions_in_preview:" + ",".join(unexpected))
    if any(a in FILL_ACTIONS for a in action_names) and not allow_fill_apply:
        blockers.append("fill_or_partial_fill_detected_requires_allow_fill_apply")
    if apply_local and not bool(effective.get("apply_local")):
        blockers.append("apply_local_requested_but_governance_effective_false")
    if build_d3_preview and bool(getattr(cfg, "enable_phase_d3_actual_exit_submit", False)):
        blockers.append("d3_preview_blocked_because_actual_exit_submit_enabled")
    if (build_d2_plan or build_d3_preview) and not allow_fill_apply:
        warnings.append("d2_d3_requested_but_fill_apply_not_allowed_effective_false")

    apply_report: Optional[Dict[str, Any]] = None
    actionable_for_apply = bool(action_names - {"kept_open", "no_live_snapshot"})
    apply_live_orders_snapshot = _extract_snapshots_from_preview_actions(proposed_actions)
    if apply_local and not blockers and actionable_for_apply:
        # Reuse the exact read-only snapshots from preview. This is critical for
        # live closeout: the preview may have polled Coinbase and observed a
        # final CANCELLED/REJECTED/EXPIRED status, while the apply step itself
        # must not depend on a second poll or silently fall back to no_snapshot.
        # The underlying orchestrator remains the single owner of local writes.
        apply_report = build_phase_c43_lifecycle_orchestrator_report(
            cfg=cfg,
            ticker=selected or "ALL",
            order_store=store,
            state_store=state,
            coinbase_client=None,
            live_orders_snapshot=apply_live_orders_snapshot,
            allow_coinbase_poll=False,
            apply_local=True,
            build_d2_plan=bool(effective.get("build_d2_plan")) and allow_fill_apply,
            persist_d2_plan=bool(effective.get("persist_d2_plan")) and allow_fill_apply,
            build_d3_preview=bool(effective.get("build_d3_preview")) and allow_fill_apply,
        )

    final_counts = [o for o in store.open_entry_orders(ticker=selected or None) if _is_c43_open_entry_order(o)]
    status = _derive_closeout_status(
        governance=governance,
        preview_report=preview_report,
        apply_report=apply_report,
        request_apply_local=apply_local,
        allow_fill_apply=allow_fill_apply,
        blockers=blockers,
    )
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C44_CLOSEOUT_PHASE,
        "status": status,
        "ticker": selected or "ALL",
        "requested": {
            "allow_coinbase_poll": bool(allow_coinbase_poll),
            "apply_local": bool(apply_local),
            "build_d2_plan": bool(build_d2_plan),
            "persist_d2_plan": bool(persist_d2_plan),
            "build_d3_preview": bool(build_d3_preview),
            "allow_fill_apply": bool(allow_fill_apply),
            "using_provided_snapshots": bool(live_orders_snapshot),
        },
        "governance_report": governance,
        "local_open_c43_before": len(open_orders),
        "local_open_c43_after": len(final_counts),
        "preview_report": preview_report,
        "apply_report": apply_report,
        "action_summary": _action_summary(proposed_actions),
        "blockers": blockers,
        "warnings": warnings,
        "safety_policy": {
            "uses_governance_effective_flags": True,
            "preview_before_apply": True,
            "default_is_read_only_preview": True,
            "coinbase_poll_is_read_only": True,
            "never_submits_to_coinbase": True,
            "never_cancels_on_coinbase": True,
            "never_replaces_on_coinbase": True,
            "never_submits_live_sell_orders": True,
            "d3_preview_forces_submit_live_false": True,
            "positions_opened_only_after_fill_evidence": True,
            "fill_apply_requires_explicit_allow_fill_apply": True,
        },
        "next_step": "Bij open status niets toepassen. Bij cancelled/rejected/expired: run met --apply-local na preview. Bij filled/partial: gebruik --allow-fill-apply en D.2/D.3 preview pas na inspectie.",
    })


def load_live_order_snapshots_from_file(path: Optional[str | Path]) -> Optional[List[Dict[str, Any]]]:
    return _load_snapshot_file(path)


__all__ = [
    "C44_CLOSEOUT_PHASE",
    "build_phase_c44_poll_to_apply_closeout_report",
    "load_live_order_snapshots_from_file",
]
