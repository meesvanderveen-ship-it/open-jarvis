from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.exit_target_source_policy import build_exit_target_source_policy_report
from bot.live_order_size_policy import live_order_size_policy_report, validate_exit_quote_size
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE
from bot.order_store import OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import reserved_base_for_matching_open_d3_orders
from bot.state_store import StateStore

PHASE = "controlled_stop_market_exit_plan_v1"
ZERO = Decimal("0")
OPEN_EQUIVALENT_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "open",
    "partially_filled",
    "cancel_pending",
    "replace_pending",
}


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
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").strip().upper().replace("/", "-")


def _open_d3_exit_orders(store: OrderStore, *, ticker: str, linked_position_id: str = "") -> List[Dict[str, Any]]:
    linked = str(linked_position_id or "").strip()
    selected_ticker = _normalize_ticker(ticker)
    orders: List[Dict[str, Any]] = []
    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("status") or "").strip().lower() not in OPEN_EQUIVALENT_STATUSES:
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if linked and str(order.get("linked_position_id") or "").strip() != linked:
            continue
        orders.append(dict(order))
    return orders


def _position_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _stop_breached(position: Dict[str, Any], market_context: Dict[str, Any]) -> bool:
    reasons = [str(x) for x in market_context.get("reasons") or []]
    reasons.extend(str(position.get(key) or "") for key in ("last_heartbeat_reason", "last_full_position_review_result"))
    if any("stop_breached_or_below_invalidation" in reason or "close_position" in reason for reason in reasons):
        return True
    current = _to_decimal(market_context.get("current_price") or market_context.get("mid_price"), "0")
    stop = _to_decimal(position.get("stop_price") or position.get("invalidation_price"), "0")
    return bool(current > ZERO and stop > ZERO and current <= stop)


def build_controlled_stop_market_exit_plan(
    *,
    ticker: str,
    linked_position_id: str = "",
    position: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    cfg: Any = None,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    cancel_verified: bool = False,
    coinbase_lookup_succeeded: Optional[bool] = None,
    coinbase_available_base: Any = None,
    cancel_exchange_status: str = "",
    partial_fill_during_cancel: bool = False,
    terminal_fill_evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a preview-only stop/market-exit plan.

    This report never submits, cancels, replaces or applies. It only describes
    the ACK-gated sequence required when a stop is breached while an existing
    D.3 TP SELL is still open above market.
    """
    selected_ticker = _normalize_ticker(ticker)
    market = dict(market_context or {})
    store = order_store or OrderStore()
    state = state_store or StateStore()
    provided_position = dict(position) if isinstance(position, dict) else None
    position = provided_position or state.get_position(selected_ticker) or {}
    selected_linked = str(linked_position_id or position.get("recovery_linked_position_id") or position.get("phase_c43_exchange_order_id") or "").strip()
    open_exits = _open_d3_exit_orders(store, ticker=selected_ticker, linked_position_id=selected_linked)
    current_price = _to_decimal(market.get("current_price") or market.get("mid_price"), "0")
    max_quote = _to_decimal(getattr(cfg, "controlled_stop_exit_max_quote_usd", "25.00"), "25.00")
    max_slippage_pct = _to_decimal(getattr(cfg, "controlled_stop_exit_max_slippage_pct", "0.0100"), "0.0100")
    order_type = str(getattr(cfg, "controlled_stop_exit_order_type", "near_market_limit_ioc") or "").strip().lower()
    route_enabled = bool(getattr(cfg, "enable_controlled_stop_market_exits", False)) if cfg is not None else False
    autonomous_cancel_enabled = bool(getattr(cfg, "enable_autonomous_stop_exit_cancel", False)) if cfg is not None else False
    autonomous_submit_enabled = bool(getattr(cfg, "enable_autonomous_stop_exit_submit", False)) if cfg is not None else False
    autonomous_apply_enabled = bool(getattr(cfg, "enable_autonomous_stop_exit_apply", False)) if cfg is not None else False
    mode_b_ack_valid = bool(
        str(getattr(cfg, "mode_b_controlled_stop_exit_ack", "") or "").strip()
        == MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
    )
    mode_c_market_ack_valid = bool(str(getattr(cfg, "mode_c_market_order_ack", "") or "").strip() == MODE_C_MARKET_ORDER_ACK_VALUE)
    mode_c_market_flags_enabled = bool(
        getattr(cfg, "market_order_enabled", False)
        and getattr(cfg, "enable_market_orders", False)
        and getattr(cfg, "allow_market_orders", False)
    )
    require_cancel_first = bool(getattr(cfg, "controlled_stop_exit_require_open_tp_cancel_first", True)) if cfg is not None else True
    position_base = _position_base(position)
    reserved_base = reserved_base_for_matching_open_d3_orders(
        store,
        ticker=selected_ticker,
        position=position,
        linked_position_id=selected_linked,
    )
    available_after_reservations = max(ZERO, position_base - reserved_base)
    duplicate_exit = len(open_exits) > 1
    oversell = bool(reserved_base > position_base and position_base > ZERO)
    stop_breached = _stop_breached(position, market)
    open_tp_above_market = any(
        _to_decimal(order.get("limit_price"), "0") > current_price > ZERO
        for order in open_exits
    )
    first_order = open_exits[0] if open_exits else {}
    exit_target_policy = build_exit_target_source_policy_report(
        cfg=cfg,
        position=position,
        market_context=market,
        current_mid=current_price,
        risk_reward_fallback_target=first_order.get("limit_price"),
    )
    stale_tp_blocks_stop_exit = bool(stop_breached and open_tp_above_market and open_exits)
    blockers: List[str] = []
    warnings: List[str] = []
    safety_checks: Dict[str, bool] = {
        "sell_only": True,
        "spot_position_exists_locally": bool(position),
        "sell_base_lte_local_position_base": True,
        "sell_base_lte_coinbase_available_base_when_available": True,
        "sell_base_plus_open_reserved_lte_local_position_base": True,
        "no_duplicate_open_d3_exit": not duplicate_exit,
        "no_market_orders": order_type == "near_market_limit_ioc",
        "no_naked_sell": bool(position_base > ZERO),
        "local_apply_requires_terminal_coinbase_evidence": True,
        "cancel_requires_exchange_order_id": True,
        "market_or_ioc_under_quote_cap": True,
        "coinbase_lookup_required_before_action": True,
        "order_and_position_store_coherent": not oversell,
    }
    if not position:
        blockers.append("position_not_found")
    if str(position.get("status") or "").strip().lower() != "open":
        blockers.append("position_not_open")
    if not stop_breached:
        blockers.append("stop_breach_not_detected")
    if not open_exits:
        blockers.append("open_d3_tp_order_not_found")
    if duplicate_exit:
        blockers.append("duplicate_open_d3_exit_orders_block_second_sell")
    if oversell:
        blockers.append("open_d3_exit_reservation_exceeds_position_base")
    if current_price <= ZERO:
        blockers.append("current_market_price_required")
    if order_type != "near_market_limit_ioc":
        blockers.append("unsupported_controlled_stop_exit_order_type")
    if open_exits and not open_tp_above_market:
        warnings.append("open_tp_order_not_above_current_market")

    if require_cancel_first and open_exits and not cancel_verified:
        market_sell_candidate_base = ZERO
    else:
        market_sell_candidate_base = available_after_reservations if not cancel_verified else position_base
    if coinbase_available_base is not None:
        cb_available = max(ZERO, _to_decimal(coinbase_available_base, "0"))
        if market_sell_candidate_base > cb_available:
            safety_checks["sell_base_lte_coinbase_available_base_when_available"] = False
            blockers.append("coinbase_available_base_below_candidate_sell_base")
    else:
        cb_available = None
    estimated_quote = market_sell_candidate_base * current_price if current_price > ZERO else ZERO
    quote_policy = validate_exit_quote_size(
        estimated_quote=estimated_quote,
        cfg=cfg,
        label="CONTROLLED_STOP_EXIT",
        is_full_close=True,
    )
    quote_policy_blockers = list(quote_policy["blockers"])
    if not (require_cancel_first and open_exits and not cancel_verified and estimated_quote == ZERO):
        blockers.extend(quote_policy_blockers)
    warnings.extend(quote_policy["warnings"])
    if estimated_quote > max_quote:
        safety_checks["market_or_ioc_under_quote_cap"] = False
        blockers.append("controlled_stop_exit_quote_cap_exceeded")
    if market_sell_candidate_base > position_base:
        safety_checks["sell_base_lte_local_position_base"] = False
        blockers.append("candidate_sell_base_exceeds_local_position_base")
    if market_sell_candidate_base + (reserved_base if not cancel_verified else ZERO) > position_base and position_base > ZERO:
        safety_checks["sell_base_plus_open_reserved_lte_local_position_base"] = False
        blockers.append("candidate_sell_plus_open_reserved_exceeds_position_base")
    if open_exits and not str(first_order.get("exchange_order_id") or first_order.get("order_id") or "").strip():
        safety_checks["cancel_requires_exchange_order_id"] = False
        blockers.append("existing_tp_exchange_order_id_required_for_cancel")
    if coinbase_lookup_succeeded is False:
        safety_checks["coinbase_lookup_required_before_action"] = False
        blockers.append("coinbase_lookup_failed")
    normalized_cancel_status = str(cancel_exchange_status or "").strip().lower()
    if normalized_cancel_status and normalized_cancel_status not in {"cancelled", "canceled"}:
        blockers.append("tp_cancel_status_not_verified_cancelled")
        warnings.append("unknown_or_non_cancelled_exchange_status_blocks_stop_sell_and_local_state_write")
    if partial_fill_during_cancel:
        blockers.append("partial_fill_during_cancel_reconcile_partial_first")
        warnings.append("partial_fill_detected_during_cancel_recompute_available_base_before_stop_sell")

    fill_evidence = dict(terminal_fill_evidence or {})
    fill_evidence_valid = bool(
        str(fill_evidence.get("normalized_status") or "").strip().lower() == "filled"
        and (
            _to_decimal(fill_evidence.get("filled_base"), "0") > ZERO
            or int(fill_evidence.get("fill_count") or 0) > 0
        )
    )
    status = "blocked_review_required"
    if not blockers and open_tp_above_market:
        status = "controlled_stop_exit_plan_ready"
    elif blockers == ["stop_breach_not_detected"]:
        status = "no_controlled_stop_exit_trigger"

    return _json_safe(
        {
            "generated_at": _now_iso(),
            "phase": PHASE,
            "status": status,
            "ticker": selected_ticker,
            "position_source": "provided_runtime_position" if provided_position is not None else "state_store",
            "linked_position_id": selected_linked,
            "stop_breached_or_below_invalidation": stop_breached,
            "stop_breach_detected": stop_breached,
            "open_tp_order_above_market": open_tp_above_market,
            "open_tp_above_market_detected": open_tp_above_market,
            "stale_tp_blocks_stop_exit": stale_tp_blocks_stop_exit,
            "controlled_stop_exit_next_step": "cancel_existing_tp_first" if stale_tp_blocks_stop_exit and not cancel_verified else ("prepare_stop_sell_preview" if cancel_verified else "review_blockers"),
            "safe_to_apply_stop_exit_now": False,
            "why_not_safe_to_apply": (
                "cancel_existing_tp_must_be_verified_first"
                if stale_tp_blocks_stop_exit and not cancel_verified
                else "terminal_fill_evidence_and_explicit_apply_ack_required"
            ),
            "exit_target_source_policy": exit_target_policy,
            "duplicate_exit_detected": duplicate_exit,
            "oversell_detected": oversell,
            "open_d3_exit_count": len(open_exits),
            "current_price": str(current_price),
            "position_base": str(position_base),
            "reserved_base_open_exit_orders": str(reserved_base),
            "available_base_minus_reserved_base": str(available_after_reservations),
            "coinbase_available_base": None if cb_available is None else str(cb_available),
            "config": {
                "enable_controlled_stop_market_exits": route_enabled,
                "enable_autonomous_stop_exit_cancel": autonomous_cancel_enabled,
                "enable_autonomous_stop_exit_submit": autonomous_submit_enabled,
                "enable_autonomous_stop_exit_apply": autonomous_apply_enabled,
                "mode_b_ack_valid": mode_b_ack_valid,
                "mode_c_market_order_flags_enabled": mode_c_market_flags_enabled,
                "mode_c_market_order_ack_valid": mode_c_market_ack_valid,
                "mode_c_stop_exit_relation": "mode_b_controlled_stop_governance_remains_primary",
                "controlled_stop_exit_max_quote_usd": str(max_quote),
                "controlled_stop_exit_require_open_tp_cancel_first": require_cancel_first,
                "controlled_stop_exit_order_type": order_type,
                "controlled_stop_exit_max_slippage_pct": str(max_slippage_pct),
            },
            "live_order_size_policy": live_order_size_policy_report(cfg),
            "exit_quote_policy": quote_policy,
            "controlled_market_sell_preview": {
                "ready_after_cancel_verified": bool(not blockers and cancel_verified and market_sell_candidate_base > ZERO),
                "sell_base": str(market_sell_candidate_base),
                "estimated_quote": str(estimated_quote),
                "order_type": order_type,
                "max_slippage_pct": str(max_slippage_pct),
                "sizing_rule": "sell_base <= available base minus reserved base; after cancel verification reservation must be zero before submit",
                "order_modes": ["near_market_limit_ioc"],
                "submit_requires_separate_ack": True,
                "fill_evidence_required_before_local_apply": True,
                "autonomous_route_enabled": route_enabled,
                "autonomous_cancel_enabled": autonomous_cancel_enabled,
                "autonomous_submit_enabled": autonomous_submit_enabled,
                "autonomous_apply_enabled": autonomous_apply_enabled,
                "autonomous_action_mode": (
                    "eligible_if_all_guards_green"
                    if route_enabled and autonomous_cancel_enabled and autonomous_submit_enabled and autonomous_apply_enabled and mode_b_ack_valid
                    else "preview_only"
                ),
                "mode_c_market_order_relation": (
                    "mode_c_flags_present_but_stop_exit_apply_still_requires_mode_b_or_explicit_stop_governance"
                    if mode_c_market_flags_enabled
                    else "mode_c_not_armed"
                ),
            },
            "cancel_existing_tp_preview": {
                "required_first": bool(require_cancel_first and open_exits),
                "ready": bool(open_exits and str(first_order.get("exchange_order_id") or first_order.get("order_id") or "").strip()),
                "cancel_verified": bool(cancel_verified),
                "exchange_cancel_status": normalized_cancel_status,
                "partial_fill_during_cancel": bool(partial_fill_during_cancel),
                "exchange_order_id": str(first_order.get("exchange_order_id") or first_order.get("order_id") or ""),
            },
            "local_apply_preview": {
                "fill_evidence_valid": fill_evidence_valid,
                "proposed_action": "apply_filled_stop_exit" if fill_evidence_valid else "await_terminal_fill_evidence",
                "state_write_allowed_now": bool(
                    route_enabled
                    and autonomous_apply_enabled
                    and mode_b_ack_valid
                    and fill_evidence_valid
                    and not blockers
                ),
                "mode_b_ack_valid": mode_b_ack_valid,
            },
            "existing_tp_order": {
                "client_order_id": str(first_order.get("client_order_id") or ""),
                "exchange_order_id": str(first_order.get("exchange_order_id") or first_order.get("order_id") or ""),
                "linked_position_id": str(first_order.get("linked_position_id") or ""),
                "limit_price": str(first_order.get("limit_price") or ""),
                "size_base": str(first_order.get("size_base") or ""),
                "remaining_size": str(first_order.get("remaining_size") or ""),
            },
            "operator_sequence": [
                "cancel_existing_tp_after_exact_ack",
                "verify_cancelled_on_coinbase",
                "prepare_controlled_market_or_near_market_ioc_sell",
                "submit_sell_only_after_separate_exact_ack",
                "require_fill_evidence_before_local_apply",
                "apply_local_fill_only_after_separate_exact_ack",
            ],
            "proposed_next_action": "ack_cancel_existing_tp_first" if status == "controlled_stop_exit_plan_ready" else "review_blockers",
            "no_coinbase_submit": True,
            "no_coinbase_cancel": True,
            "no_coinbase_replace": True,
            "no_state_write": True,
            "state_write_performed": False,
            "second_sell_blocked_until_cancel_verified": bool(open_exits and not cancel_verified),
            "safety_checks": safety_checks,
            "blockers": blockers,
            "warnings": warnings,
        }
    )


__all__ = ["PHASE", "build_controlled_stop_market_exit_plan"]
