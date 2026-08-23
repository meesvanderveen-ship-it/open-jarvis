from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report
from bot.phase_c43_lifecycle_orchestrator import build_phase_c43_lifecycle_orchestrator_report
from bot.phase_d3_open_exit_lifecycle_manager import (
    build_phase_d3_open_exit_lifecycle_report,
    scan_open_d3_exit_lifecycle_orders,
)
from bot.state_store import StateStore

SERVICE_PHASE = "C4.4.1_lifecycle_orchestrator_service_hook"


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


def _build_coinbase_client() -> Any:
    from bot.coinbase_client import CoinbaseClient

    return CoinbaseClient()


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_str(cfg: Any, name: str, default: str) -> str:
    value = getattr(cfg, name, default)
    text = str(value or "").strip()
    return text or default


def _open_d3_exit_orders(store: OrderStore, *, ticker: str = "") -> list[Dict[str, Any]]:
    return scan_open_d3_exit_lifecycle_orders(store, ticker=ticker)


def _order_identity(order: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticker": str(order.get("ticker") or order.get("product_id") or ""),
        "client_order_id": str(order.get("client_order_id") or ""),
        "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
        "linked_position_id": str(order.get("linked_position_id") or ""),
        "side": str(order.get("side") or ""),
        "status": str(order.get("status") or ""),
        "phase": str(order.get("phase") or ""),
        "size_base": str(order.get("size_base") or ""),
        "remaining_size": str(order.get("remaining_size") or ""),
        "limit_price": str(order.get("limit_price") or ""),
    }


def build_phase_c43_lifecycle_service_report(
    *,
    cfg: Any,
    ticker: str = "",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    cycle_type: str = "manual",
    source: str = "service_hook",
) -> Dict[str, Any]:
    """Run the lifecycle orchestrator as a safe bot-cycle maintenance hook.

    The hook is intentionally conservative:
    - disabled via ENABLE_PHASE_C43_LIFECYCLE_ORCHESTRATOR=false;
    - scans all C.4.3 open entry orders and D.3 open exit orders by default;
    - does not poll Coinbase unless PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL=true;
    - does not mutate local state unless PHASE_C43_LIFECYCLE_APPLY_LOCAL=true;
    - D.3 open-exit lifecycle polling remains report-only; terminal statuses
      propose the next action but never apply local state from this service hook;
    - never submits/cancels/replaces Coinbase orders and never submits live SELLs.
    """
    enabled = _cfg_bool(cfg, "enable_phase_c43_lifecycle_orchestrator", True)
    generated_at = _now_iso()
    if not enabled:
        return {
            "generated_at": generated_at,
            "phase": SERVICE_PHASE,
            "status": "disabled",
            "cycle_type": cycle_type,
            "source": source,
            "ticker": ticker or "ALL",
            "safety_policy": _service_safety_policy(),
            "orchestrator_report": None,
        }

    requested_allow_poll = _cfg_bool(cfg, "phase_c43_lifecycle_allow_coinbase_poll", False)
    requested_apply_local = _cfg_bool(cfg, "phase_c43_lifecycle_apply_local", False)
    requested_build_d2 = _cfg_bool(cfg, "phase_c43_lifecycle_build_d2_plan", False)
    requested_persist_d2 = _cfg_bool(cfg, "phase_c43_lifecycle_persist_d2_plan", False)
    requested_build_d3 = _cfg_bool(cfg, "phase_c43_lifecycle_build_d3_preview", False)

    store = order_store or OrderStore(
        path=_cfg_str(cfg, "phase_c43_lifecycle_order_store_path", "state/open_orders.json"),
        log_path=_cfg_str(cfg, "phase_c43_lifecycle_order_events_path", "logs/order_events.jsonl"),
        max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))),
    )
    state = state_store or StateStore()

    # Avoid constructing/using a Coinbase client when there are no local C.4.3
    # open orders. This keeps the default service hook lightweight and avoids
    # unnecessary API setup during ordinary observe-only cycles.
    open_c43_orders = [
        o for o in store.open_entry_orders(ticker=ticker or None)
        if str(o.get("mode") or "").lower() == "live"
        and str(o.get("execution_action") or "").lower() == "place_limit_buy"
        and (o.get("opened_via_phase_c43") or str(o.get("source_mode") or "").lower() == "autonomous_small_live")
    ]
    open_d3_exit_orders = _open_d3_exit_orders(store, ticker=ticker)
    governance_orders = open_c43_orders + open_d3_exit_orders

    governance = build_phase_c43_lifecycle_governance_report(
        cfg=cfg,
        local_open_c43_orders=governance_orders,
        ticker=ticker,
        cycle_type=cycle_type,
        source=source,
    )
    effective = governance.get("effective_flags") or {}
    allow_poll = bool(effective.get("allow_coinbase_poll", False))
    apply_local = bool(effective.get("apply_local", False))
    build_d2 = bool(effective.get("build_d2_plan", False))
    persist_d2 = bool(effective.get("persist_d2_plan", False))
    build_d3 = bool(effective.get("build_d3_preview", False))

    client = None
    if allow_poll and (open_c43_orders or open_d3_exit_orders):
        client = coinbase_client if coinbase_client is not None else _build_coinbase_client()

    if open_c43_orders:
        report = build_phase_c43_lifecycle_orchestrator_report(
            cfg=cfg,
            ticker=ticker,
            order_store=store,
            state_store=state,
            coinbase_client=client,
            allow_coinbase_poll=bool(client),
            apply_local=apply_local,
            build_d2_plan=build_d2,
            persist_d2_plan=persist_d2,
            build_d3_preview=build_d3,
        )
    else:
        report = {
            "generated_at": generated_at,
            "phase": "C4.4_D3.3_lifecycle_orchestrator_v1",
            "status": "skipped_no_open_c43_orders",
            "ticker": ticker or "ALL",
            "mode": "preview_read_only",
            "local_c43_open_orders_seen": 0,
            "coinbase_call_attempted": False,
            "coinbase_call_succeeded": False,
            "snapshot_count": 0,
            "proposed_actions": [],
            "applied_actions": [],
            "d2_reports": [],
            "d3_previews": [],
            "errors": [],
            "skip_reason": "d3_open_exit_lifecycle_runs_independently",
        }
    d3_reports = []
    d3_errors = []
    for order in open_d3_exit_orders:
        try:
            d3_reports.append(
                build_phase_d3_open_exit_lifecycle_report(
                    ticker=str(order.get("ticker") or order.get("product_id") or ""),
                    client_order_id=str(order.get("client_order_id") or ""),
                    exchange_order_id=str(order.get("exchange_order_id") or order.get("order_id") or ""),
                    linked_position_id=str(order.get("linked_position_id") or ""),
                    order_store=store,
                    state_store=state,
                    coinbase_client=client,
                    allow_coinbase_poll=bool(client),
                    apply_local=False,
                )
            )
        except Exception as exc:
            d3_errors.append(
                {
                    "order": _order_identity(order),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    status = "completed"
    if report.get("errors") or d3_errors:
        status = "completed_with_errors"
    return _json_safe({
        "generated_at": generated_at,
        "phase": SERVICE_PHASE,
        "status": status,
        "cycle_type": cycle_type,
        "source": source,
        "ticker": ticker or "ALL",
        "config": {
            "enabled": enabled,
            "requested_allow_coinbase_poll": requested_allow_poll,
            "requested_apply_local": requested_apply_local,
            "requested_build_d2_plan": requested_build_d2,
            "requested_persist_d2_plan": requested_persist_d2,
            "requested_build_d3_preview": requested_build_d3,
            "effective_allow_coinbase_poll": allow_poll,
            "effective_apply_local": apply_local,
            "effective_build_d2_plan": build_d2,
            "effective_persist_d2_plan": persist_d2,
            "effective_build_d3_preview": build_d3,
            "order_store_path": str(store.path),
            "order_events_path": str(store.log_path),
        },
        "governance_report": governance,
        "local_open_c43_orders_precheck": len(open_c43_orders),
        "local_open_d3_exit_orders_precheck": len(open_d3_exit_orders),
        "local_open_d3_exit_orders": [_order_identity(o) for o in open_d3_exit_orders[:20]],
        "coinbase_client_constructed": bool(client),
        "orchestrator_report": report,
        "d3_open_exit_lifecycle_reports": d3_reports,
        "d3_open_exit_lifecycle_errors": d3_errors,
        "summary": {
            "local_c43_open_orders_seen": report.get("local_c43_open_orders_seen", 0),
            "local_d3_open_exit_orders_seen": len(open_d3_exit_orders),
            "coinbase_call_attempted": report.get("coinbase_call_attempted", False),
            "d3_coinbase_call_attempted": any(bool(r.get("coinbase_call_attempted")) for r in d3_reports),
            "coinbase_call_succeeded": bool(report.get("coinbase_call_succeeded", False))
            or any(bool(r.get("coinbase_call_succeeded")) for r in d3_reports),
            "snapshot_count": int(report.get("snapshot_count", 0) or 0)
            + sum(1 for r in d3_reports if r.get("normalized_status")),
            "proposed_actions": len(report.get("proposed_actions") or []),
            "d3_proposed_actions": [
                {
                    "client_order_id": r.get("client_order_id"),
                    "exchange_order_id": r.get("exchange_order_id"),
                    "linked_position_id": r.get("linked_position_id"),
                    "normalized_status": r.get("normalized_status"),
                    "proposed_action": r.get("proposed_action"),
                    "status": r.get("status"),
                }
                for r in d3_reports
            ],
            "applied_actions": len(report.get("applied_actions") or []),
            "d3_applied_actions": 0,
            "d2_reports": len(report.get("d2_reports") or []),
            "d3_previews": len(report.get("d3_previews") or []),
            "errors": len(report.get("errors") or []) + len(d3_errors),
        },
        "safety_policy": _service_safety_policy(),
    })


def _service_safety_policy() -> Dict[str, bool]:
    return {
        "default_hook_is_preview_only": True,
        "coinbase_poll_requires_explicit_flag_and_open_local_order": True,
        "apply_local_requires_explicit_flag": True,
        "governance_effective_flags_gate_raw_config": True,
        "never_submits_to_coinbase": True,
        "never_cancels_on_coinbase": True,
        "never_submits_live_sell_orders": True,
        "d3_open_exit_poll_is_read_only": True,
        "d3_terminal_status_proposes_apply_only": True,
        "d3_apply_requires_separate_ack_outside_service_hook": True,
        "d3_preview_forces_submit_live_false": True,
        "positions_opened_only_after_fill_evidence": True,
    }


__all__ = ["SERVICE_PHASE", "build_phase_c43_lifecycle_service_report"]
