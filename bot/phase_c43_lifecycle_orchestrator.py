from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.atomic_io import process_lock
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot, normalize_coinbase_order_snapshot
from bot.order_lifecycle import OPEN_ORDER_STATUSES, is_open_order_status, normalize_order_status
from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import (
    _C43_LIFECYCLE_APPLY_AUTHORITY,
    _lifecycle_mutation_lock_path,
    reconcile_phase_c43_fills_to_positions,
)
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY, build_d2_exit_market_context, build_phase_d2_position_executor_report
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report
from bot.state_store import StateStore

C43_LIFECYCLE_PHASE = "C4.4_D3.3_lifecycle_orchestrator_v1"
FINAL_CANCEL_STATUSES = {"cancelled", "expired", "rejected"}
# Compatibility name for report consumers.  Classification itself uses the
# canonical predicate so every non-terminal exchange status remains reserved.
OPEN_STATUSES = OPEN_ORDER_STATUSES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
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


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").strip().upper()


def _is_c43_live_entry_order(order: Dict[str, Any]) -> bool:
    if str(order.get("side") or "").upper() != "BUY":
        return False
    if str(order.get("mode") or "").lower() != "live":
        return False
    if str(order.get("execution_action") or "").lower() != "place_limit_buy":
        return False
    return bool(order.get("opened_via_phase_c43") or str(order.get("source_mode") or "").lower() == "autonomous_small_live")


def _local_c43_orders(store: OrderStore, *, ticker: Optional[str] = None, include_final: bool = False) -> List[Dict[str, Any]]:
    selected = _normalize_ticker(ticker)
    source = store.all_orders() if include_final else store.open_entry_orders(ticker=selected or None)
    out: List[Dict[str, Any]] = []
    for order in source:
        if not _is_c43_live_entry_order(order):
            continue
        if selected and _normalize_ticker(order.get("ticker")) != selected:
            continue
        out.append(order)
    out.sort(key=lambda x: str(x.get("created_at") or x.get("updated_at") or ""))
    return out


def _snapshot_key(snapshot: Dict[str, Any]) -> List[str]:
    keys = []
    for key in (snapshot.get("client_order_id"), snapshot.get("exchange_order_id"), snapshot.get("order_id")):
        text = str(key or "").strip()
        if text and text not in keys:
            keys.append(text)
    return keys


def _build_snapshot_index(snapshots: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for snap in snapshots:
        normalized = normalize_coinbase_order_snapshot(snap, fallback_local_order=snap)
        for key in _snapshot_key(normalized):
            idx[key] = normalized
    return idx


def _collect_snapshots(
    *,
    local_orders: List[Dict[str, Any]],
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshots = _build_snapshot_index(list(live_orders_snapshot or []))
    errors: List[Dict[str, str]] = []
    attempted = False
    succeeded = False

    if allow_coinbase_poll and coinbase_client is not None:
        for local in local_orders:
            oid = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
            if not oid:
                continue
            attempted = True
            try:
                snap = fetch_coinbase_order_snapshot(coinbase_client=coinbase_client, order_id=oid, local_order=local, include_fills=True)
                for key in _snapshot_key(snap):
                    snapshots[key] = snap
                succeeded = True
            except Exception as exc:  # read-only diagnostic; do not crash the whole orchestrator
                errors.append({"order_id": oid, "error_type": type(exc).__name__, "error": str(exc)})

    return {"snapshots_by_key": snapshots, "coinbase_call_attempted": attempted, "coinbase_call_succeeded": succeeded, "errors": errors}


def _classify_action(local: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cid = str(local.get("client_order_id") or "")
    oid = str(local.get("exchange_order_id") or local.get("order_id") or "")
    ticker = _normalize_ticker(local.get("ticker"))
    if not snapshot:
        return {
            "client_order_id": cid,
            "exchange_order_id": oid,
            "ticker": ticker,
            "action": "no_live_snapshot",
            "local_status": str(local.get("status") or ""),
            "proposed_local_status": str(local.get("status") or ""),
            "writes_local_state": False,
            "position_created": False,
            "d2_plan_created": False,
            "d3_preview_created": False,
            "live_exit_order_created": False,
        }

    status = normalize_order_status(snapshot.get("normalized_status") or "unknown")
    filled_base = _to_decimal(snapshot.get("filled_base"), "0")
    proposed = str(local.get("status") or "submitted").lower()
    action = "kept_open"
    if status in FINAL_CANCEL_STATUSES:
        proposed = "cancelled" if status == "cancelled" else status
        action = f"mark_{proposed}"
    elif status == "filled" and filled_base > Decimal("0"):
        proposed = "filled"
        action = "fill_to_position"
    elif status == "partially_filled" and filled_base > Decimal("0"):
        proposed = "partially_filled"
        action = "record_partial_fill"
    elif is_open_order_status(status):
        proposed = str(local.get("status") or "submitted")
        action = "kept_open"

    return {
        "client_order_id": cid,
        "exchange_order_id": oid,
        "ticker": ticker,
        "action": action,
        "local_status": str(local.get("status") or ""),
        "coinbase_status": status,
        "coinbase_raw_status": snapshot.get("raw_status"),
        "proposed_local_status": proposed,
        "filled_base": str(filled_base),
        "avg_fill_price": str(snapshot.get("avg_fill_price") or "0"),
        "snapshot": snapshot,
        "writes_local_state": action in {"mark_cancelled", "mark_expired", "mark_rejected", "fill_to_position", "record_partial_fill"},
        "position_created": False,
        "d2_plan_created": False,
        "d3_preview_created": False,
        "live_exit_order_created": False,
    }


def _apply_final_non_fill(store: OrderStore, action: Dict[str, Any]) -> Dict[str, Any]:
    status = str(action.get("proposed_local_status") or "").lower()
    cid = str(action.get("client_order_id") or "")
    snapshot = action.get("snapshot") or {}
    updates = {
        "status": status,
        "finalized_at": _now_iso(),
        "closed_at": _now_iso(),
        "remaining_size": "0",
        "remaining_quote": "0",
        "last_live_order_snapshot": snapshot,
        "lifecycle_orchestrator_note": f"coinbase_snapshot_{status}_no_position_created",
        "position_created": False,
        "d2_plan_created": False,
        "live_exit_order_created": False,
    }
    if status == "cancelled":
        updates["cancelled_at"] = _now_iso()
        event = "phase_c43_lifecycle_order_cancelled_from_snapshot"
    elif status == "expired":
        event = "phase_c43_lifecycle_order_expired_from_snapshot"
    else:
        event = "phase_c43_lifecycle_order_rejected_from_snapshot"
    updated = store.update_order(cid, updates, event_type=event)
    applied = dict(action)
    applied["applied"] = bool(updated)
    applied["order"] = updated
    return applied


def _resolve_lifecycle_order_record_id(
    *,
    order_store: OrderStore,
    state_store: StateStore,
    ticker: str,
    applied_actions: List[Dict[str, Any]],
) -> str:
    selected = _normalize_ticker(ticker)
    for action in reversed(applied_actions):
        if _normalize_ticker(action.get("ticker")) != selected:
            continue
        candidates = [
            action.get("client_order_id"),
            (action.get("order") or {}).get("client_order_id") if isinstance(action.get("order"), dict) else None,
        ]
        for candidate in candidates:
            cid = str(candidate or "").strip()
            if cid and order_store.get_order(cid):
                return cid

    position = state_store.get_position(selected) if hasattr(state_store, "get_position") else None
    if isinstance(position, dict):
        for candidate in (
            position.get("phase_c43_client_order_id"),
            position.get("client_order_id"),
            position.get("source_order_id"),
            position.get("order_id"),
        ):
            cid = str(candidate or "").strip()
            if cid and order_store.get_order(cid):
                return cid
    return ""


def _write_order_lifecycle_metadata(
    *,
    order_store: OrderStore,
    order_id: str,
    d2_report: Optional[Dict[str, Any]],
    d3_preview: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not order_id:
        return None

    updates: Dict[str, Any] = {}
    plan = (d2_report or {}).get("plan") if isinstance(d2_report, dict) else None
    if isinstance(plan, dict):
        updates.update({
            "d2_plan_created": True,
            "d2_plan_status": str(d2_report.get("status") or ""),
            "d2_plan_id": str(plan.get("plan_id") or ""),
            "d2_plan_persisted": bool(d2_report.get("persisted")),
            "d2_plan_persisted_path": str(d2_report.get("persisted_path") or ""),
            "d2_plan_persisted_ticker_key": str(d2_report.get("persisted_ticker_key") or ""),
        })

    if isinstance(d3_preview, dict):
        updates.update({
            "d3_preview_created": True,
            "d3_preview_status": str(d3_preview.get("status") or ""),
        })
        selected_exit_intent = d3_preview.get("selected_exit_intent")
        if isinstance(selected_exit_intent, dict):
            updates.update({
                "d3_preview_label": str(selected_exit_intent.get("label") or ""),
                "d3_preview_intent_id": str(selected_exit_intent.get("intent_id") or ""),
            })

    if not updates:
        return None
    return order_store.update_order(
        order_id,
        updates,
        event_type="phase_c43_lifecycle_order_metadata_updated",
    )


def _build_d2_and_d3(
    *,
    cfg: Any,
    ticker: str,
    state_store: StateStore,
    order_store: OrderStore,
    build_d2_plan: bool,
    build_d3_preview: bool,
    persist_d2_plan: bool,
    coinbase_client: Any = None,
) -> Dict[str, Any]:
    d2_report = None
    d3_report = None
    if build_d2_plan:
        d2_report = build_phase_d2_position_executor_report(
            cfg=cfg,
            ticker=ticker,
            state_store=state_store,
            persist_plan=persist_d2_plan,
            market_context=build_d2_exit_market_context(ticker, coinbase_client=coinbase_client),
        )
    if build_d3_preview:
        d3_report = build_phase_d3_controlled_live_exit_report(
            cfg=cfg,
            ticker=ticker,
            state_store=state_store,
            order_store=order_store,
            submit_live=False,
            human_ack="",
        )
    return {"d2_report": d2_report, "d3_preview": d3_report}


def _build_phase_c43_lifecycle_orchestrator_report_unlocked(
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
    build_d3_preview: bool = False,
    persist_d2_plan: bool = False,
) -> Dict[str, Any]:
    """Coordinate C.4.3 order lifecycle -> D.2 plan -> D.3 preview.

    Default mode is read-only preview. Even in apply_local mode this function
    never submits/cancels/replaces Coinbase orders and never submits live SELLs.
    """
    selected = _normalize_ticker(ticker)
    report_ticker = selected or "ALL"
    orders = order_store or OrderStore()
    state = state_store or StateStore()
    local_orders = _local_c43_orders(orders, ticker=selected or None, include_final=False)
    snapshot_bundle = _collect_snapshots(
        local_orders=local_orders,
        coinbase_client=coinbase_client,
        allow_coinbase_poll=allow_coinbase_poll,
        live_orders_snapshot=live_orders_snapshot,
    )
    snapshots_by_key: Dict[str, Dict[str, Any]] = snapshot_bundle["snapshots_by_key"]

    proposed_actions: List[Dict[str, Any]] = []
    for local in local_orders:
        cid = str(local.get("client_order_id") or "")
        oid = str(local.get("exchange_order_id") or local.get("order_id") or "")
        snap = snapshots_by_key.get(cid) or snapshots_by_key.get(oid)
        proposed_actions.append(_classify_action(local, snap))

    applied_actions: List[Dict[str, Any]] = []
    reconcile_report: Optional[Dict[str, Any]] = None
    d2_reports: List[Dict[str, Any]] = []
    d3_previews: List[Dict[str, Any]] = []

    if apply_local:
        # First finalize non-fill states that existing C.4.3 fill reconciler does
        # not own yet. Fills/partials are delegated to the existing tested C.4.3
        # fill-to-position bridge so we do not fork that logic.
        fill_snapshots: List[Dict[str, Any]] = []
        for action in proposed_actions:
            if action["action"] in {"mark_cancelled", "mark_expired", "mark_rejected"}:
                applied_actions.append(_apply_final_non_fill(orders, action))
            elif action["action"] in {"fill_to_position", "record_partial_fill", "kept_open"} and action.get("snapshot"):
                fill_snapshots.append(action["snapshot"])

        if fill_snapshots:
            reconcile_tickers = [selected] if selected else sorted({
                _normalize_ticker(s.get("ticker") or s.get("product_id") or l.get("ticker"))
                for s in fill_snapshots
                for l in local_orders
                if _normalize_ticker(s.get("ticker") or s.get("product_id") or l.get("ticker"))
            }) or None
            reconcile_report = reconcile_phase_c43_fills_to_positions(
                cfg=cfg,
                order_store=orders,
                state_store=state,
                live_orders_snapshot=fill_snapshots,
                allow_coinbase_poll=False,
                tickers=reconcile_tickers,
                apply_local=True,
                _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
            )
            for rec_action in reconcile_report.get("actions", []) or []:
                applied_actions.append({"source": "c43_fill_reconciler", **rec_action})

        affected_tickers = sorted({
            str(a.get("ticker") or selected).upper()
            for a in applied_actions
            if a.get("action") == "filled_to_position"
        })
        # If a position already exists and user asked for D2/D3, also preview it.
        if (build_d2_plan or build_d3_preview) and not affected_tickers and selected:
            existing = state.get_position(selected) if hasattr(state, "get_position") else None
            if existing:
                affected_tickers = [selected]
        for t in affected_tickers:
            follow = _build_d2_and_d3(
                cfg=cfg,
                ticker=t,
                state_store=state,
                order_store=orders,
                build_d2_plan=build_d2_plan,
                build_d3_preview=build_d3_preview,
                persist_d2_plan=persist_d2_plan,
                coinbase_client=coinbase_client,
            )
            if isinstance(follow.get("d2_report"), dict):
                d2_reports.append(follow["d2_report"])
            if isinstance(follow.get("d3_preview"), dict):
                d3_previews.append(follow["d3_preview"])
            order_id = _resolve_lifecycle_order_record_id(
                order_store=orders,
                state_store=state,
                ticker=t,
                applied_actions=applied_actions,
            )
            _write_order_lifecycle_metadata(
                order_store=orders,
                order_id=order_id,
                d2_report=follow.get("d2_report"),
                d3_preview=follow.get("d3_preview"),
            )

    status = "preview_completed"
    if apply_local:
        status = "apply_local_completed"
    if snapshot_bundle["errors"]:
        status = f"{status}_with_snapshot_errors"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_LIFECYCLE_PHASE,
        "status": status,
        "ticker": report_ticker,
        "mode": "apply_local" if apply_local else "preview_read_only",
        "local_c43_open_orders_seen": len(local_orders),
        "coinbase_call_attempted": snapshot_bundle["coinbase_call_attempted"],
        "coinbase_call_succeeded": snapshot_bundle["coinbase_call_succeeded"],
        "snapshot_count": len(snapshots_by_key),
        "proposed_actions": proposed_actions,
        "applied_actions": applied_actions,
        "c43_reconcile_report": reconcile_report,
        "d2_reports": d2_reports,
        "d3_previews": d3_previews,
        "errors": snapshot_bundle["errors"],
        "safety_policy": {
            "default_is_read_only_preview": True,
            "apply_local_never_submits_to_coinbase": True,
            "apply_local_never_cancels_on_coinbase": True,
            "does_not_create_live_exit_orders": True,
            "d3_preview_forces_submit_live_false": True,
            "positions_opened_only_after_fill_evidence": True,
            "no_averaging_down_or_scale_in": True,
        },
        "next_step": "Gebruik preview eerst. Gebruik --apply-local alleen voor lokale lifecycle reconciliation; live SELL/exits blijven uit.",
    })


def build_phase_c43_lifecycle_orchestrator_report(
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
    build_d3_preview: bool = False,
    persist_d2_plan: bool = False,
) -> Dict[str, Any]:
    """Coordinate C.4.3 lifecycle work with a lock only for local apply."""
    if not apply_local:
        return _build_phase_c43_lifecycle_orchestrator_report_unlocked(
            cfg=cfg,
            ticker=ticker,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            live_orders_snapshot=live_orders_snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            apply_local=False,
            build_d2_plan=build_d2_plan,
            build_d3_preview=build_d3_preview,
            persist_d2_plan=persist_d2_plan,
        )

    with process_lock(
        _lifecycle_mutation_lock_path(cfg=cfg, order_store=order_store),
        allow_reentrant=True,
    ) as lock_info:
        report = _build_phase_c43_lifecycle_orchestrator_report_unlocked(
            cfg=cfg,
            ticker=ticker,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            live_orders_snapshot=live_orders_snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            apply_local=True,
            build_d2_plan=build_d2_plan,
            build_d3_preview=build_d3_preview,
            persist_d2_plan=persist_d2_plan,
        )
    report["mutation_lock"] = {
        "acquired": True,
        "reentrant": bool(lock_info.get("reentrant")),
    }
    return report


__all__ = [
    "C43_LIFECYCLE_PHASE",
    "build_phase_c43_lifecycle_orchestrator_report",
]
