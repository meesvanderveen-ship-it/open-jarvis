from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.exit_target_source_policy import build_exit_target_source_policy_report
from bot.live_order_size_policy import live_order_size_policy_report, validate_exit_quote_size
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE
from bot.order_store import OrderStore
from bot.phase_c_live_submitter import _extract_exchange_order_id
from bot.phase_d3_open_exit_lifecycle_manager import reserved_base_for_matching_open_d3_orders
from bot.product_rules import normalize_price
from bot.state_store import StateStore

PHASE = "controlled_stop_market_exit_plan_v1"
ZERO = Decimal("0")
ONE = Decimal("1")
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
    # "cancel_verified" as passed in only ever means "an actual exchange cancel was
    # confirmed." When open_exits is empty there was never a resting TP to cancel in
    # the first place, so no cancel is owed -- treat that as trivially verified for
    # readiness purposes too (apply_controlled_stop_market_exit already derives this
    # exact same way internally: cancel_verified = not needs_cancel). Without this,
    # a stop breach with no open exit order and zero real blockers still permanently
    # reported status="blocked_review_required" / next_step="review_blockers" on the
    # first (pre-cancel) preview call, because the status/next_step gates below only
    # ever checked the raw, still-default-False parameter -- confirmed live
    # 2026-07-08 on SOL-USDC, where this field alone made the position's stop-exit
    # look permanently blocked in every heartbeat's report even though the apply
    # path (which recomputes this internally) was actually still attempting the
    # submit every cycle.
    effective_cancel_verified = bool(cancel_verified) or not open_exits
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
    # No independent "must have found some exit order" blocker here: when
    # open_exits is empty there was simply never a resting TP to cancel, and
    # a stop-sell must still be able to proceed directly against the full
    # available base (see apply_controlled_stop_market_exit) -- every other
    # real risk (duplicate orders, oversell, quote cap, price validity,
    # incomplete risk state) already has its own dedicated blocker below.
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
    if not blockers and (open_tp_above_market or effective_cancel_verified):
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
            "controlled_stop_exit_next_step": "cancel_existing_tp_first" if stale_tp_blocks_stop_exit and not cancel_verified else ("prepare_stop_sell_preview" if effective_cancel_verified else "review_blockers"),
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
                "ready_after_cancel_verified": bool(not blockers and effective_cancel_verified and market_sell_candidate_base > ZERO),
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


def _normalize_cancel_result(payload: Any, *, order_id: str) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    # Coinbase's real batch_cancel response shape is
    # {"results": [{"success": bool, "order_id": "...", "failure_reason": "..."}]},
    # not a flat success_results/order_ids/cancelled_order_ids list (that shape
    # is never actually returned by the exchange -- confirmed live on
    # 2026-07-06 when a real, Coinbase-confirmed CANCELLED order was reported
    # as "cancel_not_confirmed" here, aborting Mode B before the protective
    # stop-sell was ever submitted, leaving the position unprotected after a
    # real stop breach). Check the real shape first.
    results = data.get("results") if isinstance(data.get("results"), list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        if order_id and str(item.get("order_id") or "").strip() != order_id:
            continue
        if bool(item.get("success")):
            return {"cancel_succeeded": True, "cancel_normalized_status": "cancelled", "cancel_error_message": ""}
        return {
            "cancel_succeeded": False,
            "cancel_normalized_status": "unknown",
            "cancel_error_message": str(item.get("failure_reason") or "cancel_response_not_confirmed"),
        }

    order_ids = [
        str(item).strip()
        for item in (data.get("success_results") or data.get("order_ids") or data.get("cancelled_order_ids") or [])
        if str(item).strip()
    ]
    if order_id and order_id in order_ids:
        return {"cancel_succeeded": True, "cancel_normalized_status": "cancelled", "cancel_error_message": ""}

    raw_status = str(data.get("status") or data.get("order_status") or data.get("result") or "").strip().upper()
    normalized = ""
    if raw_status in {"CANCELLED", "CANCELED"}:
        normalized = "cancelled"
    elif raw_status in {"CANCEL_PENDING", "PENDING_CANCEL"}:
        normalized = "cancel_pending"
    success = bool(data.get("success", False)) and normalized == "cancelled"
    return {
        "cancel_succeeded": success,
        "cancel_normalized_status": normalized or "unknown",
        "cancel_error_message": "" if success else "cancel_response_not_confirmed",
    }


def _normalize_fill_evidence(payload: Any) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    order = data.get("order") if isinstance(data.get("order"), dict) else data
    raw_status = str(order.get("status") or order.get("order_status") or "").strip().upper()
    filled_base = _to_decimal(
        order.get("filled_size") or order.get("filled_base") or order.get("cumulative_quantity"),
        "0",
    )
    normalized_status = "filled" if raw_status in {"FILLED"} else ("partial" if raw_status in {"OPEN", "PENDING"} and filled_base > ZERO else raw_status.lower() or "unknown")
    return {
        "raw_status": raw_status,
        "normalized_status": normalized_status,
        "filled_base": str(filled_base),
        "avg_fill_price": str(_to_decimal(order.get("average_filled_price") or order.get("avg_fill_price"), "0")),
    }


def _mark_local_order(store: OrderStore, client_order_id: str, **fields: Any) -> Dict[str, Any]:
    """Update an existing local order record without dropping its other fields.

    OrderStore.upsert_order replaces the stored record wholesale with whatever
    dict it's given -- it does not merge like StateStore.upsert_position does.
    Calling it with only {"client_order_id": ..., "status": ...} therefore
    silently discards exchange_order_id, ticker, mode, size, limit_price, etc.
    from the existing record. That's how a fully-filled stop-exit order (the
    2026-07-08 SOL-USDC incident) ended up locally marked "cancelled" with none
    of its own fill evidence attached once the terminal status was corrected --
    the record only regains completeness once every caller merges explicitly.
    """
    existing = dict(store.get_order(client_order_id) or {})
    existing.update(fields)
    existing["client_order_id"] = client_order_id
    return store.upsert_order(existing)


def apply_controlled_stop_market_exit(
    *,
    ticker: str,
    position: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None,
    cfg: Any = None,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    fill_lookup_max_attempts: int = 4,
    fill_lookup_retry_seconds: float = 0.75,
) -> Dict[str, Any]:
    """Execute the Mode B controlled stop-exit route end to end.

    Sequence (matches docs/MODE_B_CONTROLLED_STOP_EXIT_ACTIVATION_PLAN.md
    "Live Route" exactly): detect stop breach -> detect any open TP above
    market -> cancel it -> verify the cancel -> submit a governed
    near-market IOC SELL -> verify terminal fill evidence -> report the
    outcome. Applying the fill to local position state is the caller's
    responsibility (strategy_engine.py already owns that for every other
    exit path), so this function only ever touches order_store/Coinbase.

    Refuses to do anything beyond the existing preview
    (build_controlled_stop_market_exit_plan) unless
    enable_controlled_stop_market_exits, enable_autonomous_stop_exit_cancel,
    enable_autonomous_stop_exit_submit, enable_autonomous_stop_exit_apply and
    the exact MODE_B_CONTROLLED_STOP_EXIT_ACK are ALL satisfied. That is this
    codebase's own documented graduated "Mode B" activation; Mode A
    (preview-only, the prior and still-default behavior everywhere this
    isn't explicitly armed) remains valid without it.
    """
    store = order_store or OrderStore()
    state = state_store or StateStore()
    market = dict(market_context or {})

    preview = build_controlled_stop_market_exit_plan(
        ticker=ticker,
        position=position,
        market_context=market,
        cfg=cfg,
        order_store=store,
        state_store=state,
    )
    result: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": f"{PHASE}_apply",
        "ticker": _normalize_ticker(ticker),
        "preview": preview,
        "cancel_attempted": False,
        "cancel_result": None,
        "submit_attempted": False,
        "submit_result": None,
        "fill_evidence": None,
        "applied_locally": False,
    }

    if preview.get("status") == "no_controlled_stop_exit_trigger":
        result["status"] = "no_controlled_stop_exit_trigger"
        return result

    config = preview.get("config") or {}
    mode_b_armed = bool(
        config.get("enable_controlled_stop_market_exits")
        and config.get("enable_autonomous_stop_exit_cancel")
        and config.get("enable_autonomous_stop_exit_submit")
        and config.get("enable_autonomous_stop_exit_apply")
        and config.get("mode_b_ack_valid")
    )
    if not mode_b_armed:
        result["status"] = "mode_b_not_armed_preview_only"
        return result

    if coinbase_client is None:
        result["status"] = "coinbase_client_missing"
        return result

    existing_tp = preview.get("existing_tp_order") or {}
    needs_cancel = bool(preview.get("stale_tp_blocks_stop_exit"))
    # Nothing to cancel means nothing blocks sizing against the full
    # available base -- "cancel_verified" here reads as "no outstanding
    # cancel is owed," which is trivially true when there was never a
    # resting TP order in the first place.
    cancel_verified = not needs_cancel
    cancel_exchange_status = ""

    if needs_cancel:
        exchange_order_id = str(existing_tp.get("exchange_order_id") or "").strip()
        if not exchange_order_id:
            result["status"] = "existing_tp_missing_exchange_order_id_cannot_cancel"
            return result
        result["cancel_attempted"] = True
        try:
            cancel_response = coinbase_client.cancel_order(exchange_order_id)
        except Exception as exc:
            result["status"] = "cancel_request_failed"
            result["cancel_result"] = {"cancel_succeeded": False, "cancel_error_message": str(exc)}
            return result
        cancel_outcome = _normalize_cancel_result(cancel_response, order_id=exchange_order_id)
        result["cancel_result"] = cancel_outcome
        if not cancel_outcome.get("cancel_succeeded"):
            result["status"] = "cancel_not_confirmed"
            return result
        cancel_verified = True
        cancel_exchange_status = "cancelled"
        # Deliberately do NOT mark the TP order cancelled in order_store yet:
        # build_controlled_stop_market_exit_plan's own open_d3_tp_order_not_found
        # blocker requires it to still be found on record (cancel_verified is
        # a separate boolean signal, not "absent from the store") for the
        # recompute below. The local record is updated once the whole
        # sequence -- cancel, submit, fill -- has actually completed.

    # Recompute with the cancel now verified: this re-derives
    # market_sell_candidate_base against the freed-up reservation and
    # re-runs every blocker check from scratch (never trust the pre-cancel
    # preview's sizing for the actual submit).
    post_cancel_plan = build_controlled_stop_market_exit_plan(
        ticker=ticker,
        position=position,
        market_context=market,
        cfg=cfg,
        order_store=store,
        state_store=state,
        cancel_verified=cancel_verified,
        cancel_exchange_status=cancel_exchange_status,
    )
    result["post_cancel_plan"] = post_cancel_plan
    sell_preview = post_cancel_plan.get("controlled_market_sell_preview") or {}
    if post_cancel_plan.get("blockers") or not sell_preview.get("ready_after_cancel_verified"):
        result["status"] = "blocked_after_cancel_recompute"
        return result

    sell_base = _to_decimal(sell_preview.get("sell_base"), "0")
    if sell_base <= ZERO:
        result["status"] = "sell_base_zero_after_cancel_recompute"
        return result

    if needs_cancel:
        # The cancel is now a done deal on Coinbase regardless of what
        # happens next (submit failure, IOC kill, etc.) -- reflect that
        # locally so nothing downstream mistakes it for still resting.
        cancelled_client_order_id = str(existing_tp.get("client_order_id") or "").strip()
        if cancelled_client_order_id:
            _mark_local_order(store, cancelled_client_order_id, status="cancelled")

    current_price = _to_decimal(market.get("current_price") or market.get("mid_price"), "0")
    max_slippage_pct = _to_decimal(getattr(cfg, "controlled_stop_exit_max_slippage_pct", "0.0100"), "0.0100")
    if current_price <= ZERO:
        result["status"] = "current_price_required_for_ioc_limit"
        return result
    raw_limit_price = current_price * (ONE - max_slippage_pct)
    # Coinbase rejects any price with more decimals than the product's own
    # price_increment (confirmed live 2026-07-08: SOL-USDC's raw slippage-adjusted
    # price, e.g. 76.3834500, was rejected with INVALID_PRICE_PRECISION -- the
    # product's actual tick size is 0.01). Round down (not to nearest) so a SELL
    # IOC stays at least as aggressive as intended, never less.
    try:
        product_rules = coinbase_client.get_product(ticker) if coinbase_client is not None else {}
    except Exception:
        product_rules = {}
    limit_price = normalize_price(ticker, raw_limit_price, product_rules)
    if limit_price <= ZERO:
        limit_price = raw_limit_price

    ticker_compact = _normalize_ticker(ticker).replace("-", "")
    linked_position_id = str(
        (position or {}).get("recovery_linked_position_id")
        or (position or {}).get("phase_c43_exchange_order_id")
        or (position or {}).get("order_id")
        or ""
    ).strip()
    client_order_id = f"phased3-stopexit-{ticker_compact}-{linked_position_id or 'position'}-{uuid.uuid4().hex[:8]}"

    result["submit_attempted"] = True
    try:
        submit_response = coinbase_client.place_limit_order_ioc(
            ticker=ticker,
            side="SELL",
            base_size=sell_base,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )
    except Exception as exc:
        result["status"] = "ioc_submit_failed"
        result["submit_result"] = {"error": str(exc)}
        return result
    submit_dict = submit_response if isinstance(submit_response, dict) else {}
    # Coinbase nests the real order id under success_response for a normal
    # {"success": true, "success_response": {...}} accept, and this endpoint can
    # also return HTTP 200 with {"success": false, ...} for a rejected order --
    # neither shape has a top-level order_id/id, so a naive top-level-only lookup
    # silently extracts "". Reuse the same extractor already proven against real
    # Coinbase responses for live BUY submits (bot/phase_c_live_submitter.py).
    exchange_order_id = _extract_exchange_order_id(submit_dict)
    result["submit_result"] = submit_dict

    if not exchange_order_id:
        # Nothing was actually accepted onto the book -- there is no live order to
        # track locally. Writing an "open"/"live" record here with no
        # exchange_order_id previously raised an uncaught ValueError out of
        # OrderStore's own safety guard (live open order records require
        # exchange_order_id), which aborted this ticker's whole cycle before this
        # status/result was ever returned or logged -- silently losing Coinbase's
        # actual rejection reason and leaving the stop-breached position
        # unprotected with no diagnosable record of what happened. Confirmed live
        # 2026-07-08 immediately after fixing the sor_limit_ioc field name.
        result["status"] = "ioc_submit_missing_exchange_order_id"
        return result

    store.upsert_order({
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "ticker": _normalize_ticker(ticker),
        "side": "SELL",
        "status": "submitted",
        "phase": PHASE,
        "mode": "live",
        "linked_position_id": linked_position_id,
        "size_base": str(sell_base),
        "limit_price": str(limit_price),
        "execution_action": "controlled_stop_market_exit_ioc",
    })

    # An IOC order resolves near-instantly on Coinbase's matching engine, but a
    # get_order lookup taken immediately after submit can still race ahead of
    # settlement, especially when the fill sweeps many price levels (confirmed
    # live 2026-07-08: a SOL-USDC stop-exit filled completely in 18 separate
    # fills, yet the single immediate lookup here read back status "OPEN" with
    # zero filled_base, so the code concluded "no fill" and marked the order
    # cancelled locally -- while the position was, in fact, fully closed on
    # Coinbase. That desync was invisible until manually reconciled against a
    # direct balance check). Retry briefly while the exchange-reported status
    # is still non-terminal before accepting "no fill" as the final answer.
    terminal_statuses = {"FILLED", "CANCELLED", "CANCELED", "EXPIRED", "REJECTED", "FAILED"}
    fill_evidence: Dict[str, Any] = {}
    attempts = max(1, int(fill_lookup_max_attempts))
    for attempt in range(attempts):
        try:
            order_lookup = coinbase_client.get_order(exchange_order_id)
        except Exception as exc:
            result["status"] = "fill_evidence_lookup_failed"
            result["fill_evidence"] = {"error": str(exc)}
            return result
        fill_evidence = _normalize_fill_evidence(order_lookup)
        if fill_evidence.get("raw_status") in terminal_statuses or _to_decimal(fill_evidence.get("filled_base"), "0") > ZERO:
            break
        if attempt < attempts - 1:
            time.sleep(max(0.0, float(fill_lookup_retry_seconds)))
    result["fill_evidence"] = fill_evidence
    filled_base = _to_decimal(fill_evidence.get("filled_base"), "0")
    if filled_base <= ZERO:
        result["status"] = "ioc_killed_no_fill"
        _mark_local_order(store, client_order_id, status="cancelled")
        return result

    result["status"] = "filled_awaiting_local_apply"
    result["filled_base"] = str(filled_base)
    result["avg_fill_price"] = fill_evidence.get("avg_fill_price")
    _mark_local_order(store, client_order_id, status="filled", filled_size=str(filled_base))
    return result


__all__ = ["PHASE", "build_controlled_stop_market_exit_plan", "apply_controlled_stop_market_exit"]
