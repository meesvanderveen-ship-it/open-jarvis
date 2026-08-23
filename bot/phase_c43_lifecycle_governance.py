from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

GOVERNANCE_PHASE = "C4.4.2_lifecycle_poll_apply_governance"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


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


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    return _to_int(getattr(cfg, name, default), default)


def _order_identity(order: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "client_order_id": str(order.get("client_order_id") or ""),
        "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
        "ticker": str(order.get("ticker") or order.get("product_id") or "").upper(),
        "status": str(order.get("status") or ""),
        "side": str(order.get("side") or "").upper(),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
    }


def _count_orders_by_ticker(orders: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for order in orders:
        ticker = str(order.get("ticker") or order.get("product_id") or "UNKNOWN").upper()
        counts[ticker] = counts.get(ticker, 0) + 1
    return dict(sorted(counts.items()))


def _max_quote_ok(order: Dict[str, Any], max_quote: Decimal) -> bool:
    quote = _to_decimal(order.get("remaining_quote") or order.get("size_quote") or order.get("quote_size"), "0")
    if quote <= Decimal("0"):
        return True
    return quote <= max_quote


def build_phase_c43_lifecycle_governance_report(
    *,
    cfg: Any,
    local_open_c43_orders: List[Dict[str, Any]],
    ticker: str = "",
    cycle_type: str = "manual",
    source: str = "service_hook",
) -> Dict[str, Any]:
    """Decide effective lifecycle hook behavior for C.4.4.2.

    This is a control-plane guard, not an execution layer. It never calls
    Coinbase, never writes local state, never submits/cancels/replaces orders,
    and never creates live SELL orders. The service hook must use the returned
    effective flags instead of raw .env flags so that unsafe flag combinations
    degrade to preview/no-op rather than activating multiple lifecycle steps at
    once.
    """
    orders = [dict(o) for o in (local_open_c43_orders or [])]
    open_count = len(orders)

    raw = {
        "enable_phase_c43_lifecycle_orchestrator": _cfg_bool(cfg, "enable_phase_c43_lifecycle_orchestrator", True),
        "allow_coinbase_poll": _cfg_bool(cfg, "phase_c43_lifecycle_allow_coinbase_poll", False),
        "apply_local": _cfg_bool(cfg, "phase_c43_lifecycle_apply_local", False),
        "build_d2_plan": _cfg_bool(cfg, "phase_c43_lifecycle_build_d2_plan", False),
        "persist_d2_plan": _cfg_bool(cfg, "phase_c43_lifecycle_persist_d2_plan", False),
        "build_d3_preview": _cfg_bool(cfg, "phase_c43_lifecycle_build_d3_preview", False),
    }
    limits = {
        "max_poll_orders_per_cycle": max(0, _cfg_int(cfg, "phase_c43_lifecycle_max_poll_orders_per_cycle", 4)),
        "max_apply_actions_per_cycle": max(0, _cfg_int(cfg, "phase_c43_lifecycle_max_apply_actions_per_cycle", 4)),
        "max_entry_quote": str(getattr(cfg, "phase_c_max_order_quote", getattr(cfg, "autonomous_max_order_quote", "25.00"))),
    }
    policy = {
        "apply_requires_coinbase_poll": _cfg_bool(cfg, "phase_c43_lifecycle_apply_requires_coinbase_poll", True),
        "block_apply_when_live_exits_enabled": _cfg_bool(cfg, "phase_c43_lifecycle_block_apply_when_live_exits_enabled", True),
        "block_apply_when_d3_actual_exit_submit_enabled": True,
        "full_workflow_live_mode_allows_apply_before_d3_submit": _cfg_bool(cfg, "enable_full_workflow_live_mode", False),
        "no_coinbase_poll_without_open_local_order": True,
        "no_apply_without_open_local_order": True,
        "no_d2_or_d3_without_apply_local": True,
    }

    blockers: List[str] = []
    warnings: List[str] = []
    decisions: List[str] = []

    if not raw["enable_phase_c43_lifecycle_orchestrator"]:
        decisions.append("orchestrator_disabled")

    if open_count == 0:
        decisions.append("no_open_c43_orders_preview_noop")
        if raw["allow_coinbase_poll"]:
            warnings.append("allow_coinbase_poll_requested_but_no_open_orders")
        if raw["apply_local"]:
            warnings.append("apply_local_requested_but_no_open_orders")

    if raw["allow_coinbase_poll"] and open_count > limits["max_poll_orders_per_cycle"]:
        blockers.append("open_c43_orders_exceed_poll_limit")
    if raw["apply_local"] and open_count > limits["max_apply_actions_per_cycle"]:
        blockers.append("open_c43_orders_exceed_apply_limit")

    max_quote = _to_decimal(limits["max_entry_quote"], "25.00")
    oversized = [_order_identity(o) for o in orders if not _max_quote_ok(o, max_quote)]
    if oversized:
        blockers.append("open_c43_order_quote_exceeds_governance_cap")

    live_exits_enabled = _cfg_bool(cfg, "enable_live_exit_orders", False) or _cfg_bool(cfg, "autonomous_allow_exits", False)
    d3_actual_enabled = _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False)
    full_workflow_mode = _cfg_bool(cfg, "enable_full_workflow_live_mode", False)
    if raw["apply_local"] and policy["block_apply_when_live_exits_enabled"] and live_exits_enabled and not full_workflow_mode:
        blockers.append("apply_local_blocked_live_exit_flags_enabled")
    if raw["apply_local"] and d3_actual_enabled and not full_workflow_mode:
        blockers.append("apply_local_blocked_d3_actual_exit_submit_enabled")

    if raw["apply_local"] and policy["apply_requires_coinbase_poll"] and not raw["allow_coinbase_poll"]:
        blockers.append("apply_local_requires_coinbase_poll_flag")

    if raw["build_d2_plan"] and not raw["apply_local"]:
        warnings.append("build_d2_plan_requested_without_apply_local_effective_false")
    if raw["persist_d2_plan"] and not raw["build_d2_plan"]:
        warnings.append("persist_d2_plan_requested_without_build_d2_effective_false")
    if raw["build_d3_preview"] and not raw["build_d2_plan"]:
        warnings.append("build_d3_preview_requested_without_build_d2_review")

    can_poll = bool(
        raw["enable_phase_c43_lifecycle_orchestrator"]
        and raw["allow_coinbase_poll"]
        and open_count > 0
        and open_count <= limits["max_poll_orders_per_cycle"]
        and not oversized
    )
    can_apply = bool(
        raw["enable_phase_c43_lifecycle_orchestrator"]
        and raw["apply_local"]
        and open_count > 0
        and open_count <= limits["max_apply_actions_per_cycle"]
        and not blockers
    )
    build_d2 = bool(can_apply and raw["build_d2_plan"])
    persist_d2 = bool(build_d2 and raw["persist_d2_plan"])
    build_d3 = bool(can_apply and raw["build_d3_preview"])

    if can_poll:
        decisions.append("coinbase_poll_allowed_for_open_c43_orders")
    elif raw["allow_coinbase_poll"]:
        decisions.append("coinbase_poll_requested_but_effective_false")
    else:
        decisions.append("coinbase_poll_disabled_by_flag")

    if can_apply:
        decisions.append("apply_local_allowed_under_governance")
    elif raw["apply_local"]:
        decisions.append("apply_local_requested_but_effective_false")
    else:
        decisions.append("apply_local_disabled_by_flag")

    status = "preview_only"
    if blockers:
        status = "blocked_review_required"
    elif can_apply:
        status = "apply_local_governed"
    elif can_poll:
        status = "poll_only_governed"
    elif open_count == 0:
        status = "no_open_orders_noop"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": GOVERNANCE_PHASE,
        "status": status,
        "ticker": str(ticker or "ALL").upper() if ticker else "ALL",
        "cycle_type": cycle_type,
        "source": source,
        "raw_requested_flags": raw,
        "effective_flags": {
            "allow_coinbase_poll": can_poll,
            "apply_local": can_apply,
            "build_d2_plan": build_d2,
            "persist_d2_plan": persist_d2,
            "build_d3_preview": build_d3,
        },
        "limits": limits,
        "policy": policy,
        "local_open_c43_orders": {
            "count": open_count,
            "by_ticker": _count_orders_by_ticker(orders),
            "orders": [_order_identity(o) for o in orders[:20]],
            "truncated": max(0, open_count - 20),
        },
        "blockers": blockers,
        "warnings": warnings,
        "decisions": decisions,
        "safety_policy": {
            "does_not_call_coinbase": True,
            "does_not_submit_to_coinbase": True,
            "does_not_cancel_on_coinbase": True,
            "does_not_modify_local_state": True,
            "never_submits_live_sell_orders": True,
            "effective_flags_must_be_used_by_service_hook": True,
        },
    })


__all__ = ["GOVERNANCE_PHASE", "build_phase_c43_lifecycle_governance_report"]
