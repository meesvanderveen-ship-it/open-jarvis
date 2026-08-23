from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.exit_target_source_policy import build_exit_target_source_policy_report
from bot.atomic_io import process_lock, runtime_mutation_lock_path
from bot.live_order_size_policy import (
    MAX_LIVE_EXIT_ORDER_QUOTE_USDC,
    live_order_size_policy_report,
    validate_exit_quote_size,
)
from bot.live_exit_gate import (
    LiveExitBlockedError,
    append_live_exit_event,
    assert_live_exit_allowed,
    build_blocked_live_exit_event,
)
from bot.order_lifecycle import OPEN_ORDER_STATUSES, is_open_order_status
from bot.order_store import OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import (
    logical_position_id_candidates,
    order_matches_logical_position,
)
from bot.phase_d3_reservation_governance import build_phase_d3_reservation_governance_snapshot
from bot.phase_d2_position_executor import (
    D2_PLAN_STATUS_READY,
    build_phase_d2_position_executor_report,
    is_d2_manageable_open_position,
    load_position_executor_plans,
    position_protective_risk_state,
)
from bot.config import effective_phase_c_allowed_tickers
from bot.governance_constants import D3_CONTROLLED_LIVE_EXIT_ACK_VALUE
from replication.lifecycle_publisher import build_lifecycle_order_event, publish_lifecycle_event_best_effort
from bot.state_store import StateStore

ZERO = Decimal("0")
ONE = Decimal("1")
D3_PHASE = "D3_controlled_live_reduce_only_exits"
D3_READY_NO_SUBMIT = "d3_controlled_exit_ready_no_submit"
D3_SUBMITTED = "d3_controlled_live_exit_submitted"
D3_SUBMIT_ATTEMPTED = "d3_controlled_live_exit_submit_attempted"
D3_BLOCKED = "d3_controlled_exit_blocked"
D3_SUBMIT_REJECTED = "d3_controlled_exit_submit_rejected"
D3_NO_PLAN = "d3_no_ready_position_executor_plan"
D3_ACK = D3_CONTROLLED_LIVE_EXIT_ACK_VALUE
D3_MAX_EXIT_QUOTE = MAX_LIVE_EXIT_ORDER_QUOTE_USDC
D3_MAX_OPEN_EXIT_ORDERS = 4
D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE = 1
D3_MANAGED_PREFIX = "phased3-"
# Compatibility export; the persisted-order vocabulary is centralized in
# bot.order_lifecycle so D3 reservations cannot diverge from OrderStore.
D3_OPEN_STATUSES = OPEN_ORDER_STATUSES
D3_AUDIT_PATH = Path("logs/phase_d3_controlled_live_exits.jsonl")


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
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_dec(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    return _to_int(getattr(cfg, name, default), default)


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


def _explicit_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if value is None:
        return False
    return str(value).strip().lower() in {"0", "false", "no", "off"}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        return value
    try:
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment
    except Exception:
        return value


def _position_base(position: Dict[str, Any]) -> Decimal:
    positive = [
        _to_decimal(position.get(key), "0")
        for key in ("bot_managed_base", "position_size_base", "base_size")
        if _to_decimal(position.get(key), "0") > ZERO
    ]
    if positive:
        return min(positive)
    return ZERO


def _position_id(position: Dict[str, Any]) -> str:
    candidates = logical_position_id_candidates(position)
    return candidates[0] if candidates else ""


def _entry_price_from_position(position: Dict[str, Any]) -> Decimal:
    return _to_decimal(position.get("entry_price") or position.get("avg_entry_price") or position.get("average_entry_price"), "0")


def _is_d3_managed_exit_order(order: Dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id") or "")
    phase = str(order.get("phase") or "")
    mode = str(order.get("source_mode") or order.get("mode") or "")
    return str(order.get("side") or "").upper() == "SELL" and (cid.startswith(D3_MANAGED_PREFIX) or phase == D3_PHASE or mode == "phase_d3_live_exit")


def _open_d3_exit_orders(order_store: Optional[OrderStore] = None, *, ticker: Optional[str] = None, position_id: Optional[str] = None) -> List[Dict[str, Any]]:
    store = order_store or OrderStore()
    selected_ticker = _normalize_ticker(ticker)
    selected_pos = str(position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in store.open_exit_orders(ticker=selected_ticker or None):
        if not _is_d3_managed_exit_order(order):
            continue
        if selected_pos and not order_matches_logical_position(
            order,
            linked_position_id=selected_pos,
        ):
            continue
        if not is_open_order_status(order.get("status")):
            continue
        out.append(order)
    return out


def count_phase_d3_live_exit_orders(order_store: Optional[OrderStore] = None) -> Dict[str, Any]:
    orders = _open_d3_exit_orders(order_store)
    return _json_safe({
        "total_open_d3_exit_orders": len(orders),
        "tickers": sorted({_normalize_ticker(o.get("ticker")) for o in orders if _normalize_ticker(o.get("ticker"))}),
        "orders": orders,
    })


def _reserved_base_for_position(order_store: Optional[OrderStore], *, ticker: str, position_id: str) -> Decimal:
    total = ZERO
    for order in _open_d3_exit_orders(order_store, ticker=ticker, position_id=position_id):
        remaining = _to_decimal(order.get("remaining_size") or order.get("size_base"), "0")
        total += max(ZERO, remaining)
    return total


def _has_duplicate_exit_for_label(
    order_store: Optional[OrderStore],
    *,
    ticker: str,
    position_id: str,
    label: str,
) -> bool:
    for order in _open_d3_exit_orders(order_store, ticker=ticker, position_id=position_id):
        if str(order.get("d3_exit_label") or "").strip().upper() == str(label or "").strip().upper():
            return True
    return False


def _base_increment(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    for key in ("base_increment", "base_increment_size"):
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _min_order_quote(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    for key in ("quote_min_size", "min_market_funds", "min_order_quote"):
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return Decimal("1.00")


def _price_increment(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    # Coinbase quote increments describe quote-amount precision; they are not
    # executable price ticks.  Falling back to them can move a low-priced
    # asset's post-only SELL by cents (as happened for ADA), so a missing
    # price increment must fail closed instead.
    for key in ("price_increment", "price_increment_size"):
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _market_decimal(source: Dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        value = _to_decimal(source.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _relative_price_deviation(candidate: Decimal, reference: Decimal) -> Decimal:
    if candidate <= ZERO or reference <= ZERO:
        return ZERO
    return (candidate - reference).copy_abs() / reference


def _full_close_market_evidence(
    orderbook: Dict[str, Any],
    explicit_market_evidence_price: Any,
) -> Tuple[str, Decimal]:
    explicit = _to_decimal(explicit_market_evidence_price, "0")
    if explicit > ZERO:
        return "position_action_market_evidence", explicit
    for key in ("market_evidence_price", "current_price", "mid_price", "last_price"):
        value = _to_decimal(orderbook.get(key), "0")
        if value > ZERO:
            return f"orderbook_context_{key}", value
    return "missing", ZERO


def _client_order_id(*, ticker: str, position_id: str, label: str) -> str:
    clean_ticker = _normalize_ticker(ticker).replace("-", "")
    clean_label = str(label or "EXIT").replace("_", "").replace("-", "")[:12].upper()
    suffix = _now_iso().replace(":", "").replace(".", "").replace("+", "")[-18:]
    pos_part = str(position_id or "pos")[-8:].replace("-", "")
    return f"{D3_MANAGED_PREFIX}{clean_ticker}-{clean_label}-{pos_part}-{suffix}"


def build_phase_d3_full_close_exit_intent(
    *,
    cfg: Any,
    ticker: str,
    position: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    orderbook_context: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    requested_base_size: Any = None,
    label: str = "FULL_CLOSE",
    source_reason: str = "",
    market_evidence_price: Any = None,
) -> Dict[str, Any]:
    """Build a post-only D.3 discretionary full-close SELL intent.

    This is deliberately not a stop/invalidation exit route.  Stop and risk
    closes require the controlled stop-exit workflow, whose near-market IOC
    semantics and ACK gates are separate from D3 maker GTC exits.
    """
    selected_ticker = _normalize_ticker(ticker or position.get("ticker"))
    position_id = _position_id(position)
    position_base = _position_base(position)
    reserved_base = _reserved_base_for_position(order_store, ticker=selected_ticker, position_id=position_id)
    available_base = max(ZERO, position_base - reserved_base)
    max_quote = min(_cfg_dec(cfg, "phase_d3_max_exit_order_quote", D3_MAX_EXIT_QUOTE), D3_MAX_EXIT_QUOTE)
    increment = _base_increment(exchange_rules)
    price_increment = _price_increment(exchange_rules)
    min_quote = max(_min_order_quote(exchange_rules), _cfg_dec(cfg, "min_live_order_quote_usdc", Decimal("20.00")))
    orderbook = _as_dict(orderbook_context)
    best_ask = _market_decimal(orderbook, "best_ask", "ask")
    best_bid = _market_decimal(orderbook, "best_bid", "bid")
    evidence_source, market_evidence = _full_close_market_evidence(orderbook, market_evidence_price)
    max_price_deviation = _cfg_dec(cfg, "controlled_stop_exit_max_slippage_pct", Decimal("0.0100"))
    blockers: List[str] = []
    warnings: List[str] = []

    if position_base <= ZERO:
        blockers.append("position_base_missing_or_zero")
    if available_base <= ZERO:
        blockers.append("no_available_base_after_existing_exit_reservations")
    risk_state = position_protective_risk_state(position, None)
    if not risk_state["complete"]:
        blockers.append("position_risk_incomplete_stop_or_invalidation_missing")
    if best_ask <= ZERO:
        blockers.append("missing_orderbook_for_full_close")
    if price_increment <= ZERO:
        blockers.append("price_increment_missing_for_full_close")
    freshness_status = str(orderbook.get("freshness_status") or "").strip().lower()
    if freshness_status and freshness_status not in {"fresh", "current", "ok"}:
        blockers.append("full_close_orderbook_not_fresh")
    if market_evidence <= ZERO:
        blockers.append("full_close_market_evidence_missing")

    raw_limit_price = best_ask + price_increment if best_ask > ZERO and price_increment > ZERO else ZERO
    limit_price = _quantize_down(raw_limit_price, price_increment)
    if best_bid > ZERO and limit_price <= best_bid:
        blockers.append("full_close_limit_would_cross_or_touch_bid")
    price_deviation = _relative_price_deviation(limit_price, market_evidence)
    if market_evidence > ZERO and limit_price > ZERO and price_deviation > max_price_deviation:
        blockers.append("full_close_limit_price_deviates_from_market_evidence")
    requested = _to_decimal(requested_base_size, "0") if requested_base_size is not None else available_base
    if requested <= ZERO:
        requested = available_base
    requested_base = min(requested, available_base)
    if limit_price > ZERO and requested_base * limit_price > max_quote:
        requested_base = max_quote / limit_price
        warnings.append("full_close_base_clamped_to_phase_d3_max_quote")
    requested_base = _quantize_down(requested_base, increment)
    estimated_quote = requested_base * limit_price if limit_price > ZERO else ZERO
    quote_policy = validate_exit_quote_size(
        estimated_quote=estimated_quote,
        cfg=cfg,
        label=label,
        is_full_close=True,
        product_min_quote=min_quote,
    )
    blockers.extend(quote_policy["blockers"])
    warnings.extend(quote_policy["warnings"])
    if requested_base <= ZERO:
        blockers.append("sell_base_missing_or_zero_after_reservation_or_increment")
    if _has_duplicate_exit_for_label(order_store, ticker=selected_ticker, position_id=position_id, label=label):
        blockers.append("duplicate_exit_label_already_open_for_position")

    cid = _client_order_id(ticker=selected_ticker, position_id=position_id, label=label)
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "intent_id": cid,
        "client_order_id": cid,
        "ticker": selected_ticker,
        "position_id": position_id,
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "label": str(label or "FULL_CLOSE").upper(),
        "size_base": str(requested_base),
        "raw_limit_price": str(raw_limit_price),
        "limit_price": str(limit_price),
        "estimated_quote_value": str(estimated_quote),
        "price_increment_used": str(price_increment),
        "price_precision_context": "exchange_rules_price_increment" if price_increment > ZERO else "no_price_increment_available",
        "market_evidence_price": str(market_evidence),
        "market_evidence_source": evidence_source,
        "limit_price_deviation_from_market_evidence_pct": str(price_deviation),
        "max_market_evidence_deviation_pct": str(max_price_deviation),
        "requested_base_before_clamp": str(requested),
        "position_base": str(position_base),
        "reserved_base_existing_exit_orders": str(reserved_base),
        "available_base_after_reservations": str(available_base),
        "reduce_only_local": True,
        "post_only": bool(getattr(cfg, "phase_d3_exit_order_post_only", True)),
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "live_order_size_policy": live_order_size_policy_report(cfg),
        "exit_quote_policy": quote_policy,
        "source_plan_id": str(source_reason or "strategy_engine_full_workflow_full_close"),
        "source_plan_status": D2_PLAN_STATUS_READY,
        "full_close_semantics": {
            "maker_reference": "best_ask_plus_one_tick",
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "market_evidence_price": str(market_evidence),
            "market_evidence_source": evidence_source,
            "max_market_evidence_deviation_pct": str(max_price_deviation),
            "market_order_allowed": False,
            "stop_or_invalidation_route": "controlled_stop_exit_required",
        },
    })


def build_phase_d3_risk_close_exit_intent(
    *,
    cfg: Any,
    ticker: str,
    position: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    orderbook_context: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    requested_base_size: Any = None,
    label: str = "RISK_CLOSE",
    source_reason: str = "",
    market_evidence_price: Any = None,
) -> Dict[str, Any]:
    """Return a blocked D3 intent for a risk close.

    A post-only GTC at or above the ask is maker pricing, not executable stop
    protection.  Keeping this guard at the builder protects callers outside
    StrategyEngine as well as the main runtime bridge.
    """
    intent = build_phase_d3_full_close_exit_intent(
        cfg=cfg,
        ticker=ticker,
        position=position,
        order_store=order_store,
        orderbook_context=orderbook_context,
        exchange_rules=exchange_rules,
        requested_base_size=requested_base_size,
        label=str(label or "RISK_CLOSE").upper(),
        source_reason=source_reason or "risk_close_requires_controlled_stop_exit",
        market_evidence_price=market_evidence_price,
    )
    intent["blockers"] = sorted(set([*(intent.get("blockers") or []), "risk_close_requires_controlled_stop_exit_route"]))
    intent["risk_close_semantics"] = {
        "maker_limit_route_allowed": False,
        "required_route": "controlled_stop_exit",
        "market_order_allowed_by_d3": False,
        "mode_a_behavior": "preview_and_report_only",
        "mode_b_behavior": "separate_ack_gated_controlled_stop_exit",
    }
    return intent


def select_next_phase_d3_exit_intent(
    *,
    cfg: Any,
    plan: Dict[str, Any],
    position: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Select one safe live SELL intent from a D.2 plan.

    D.3 submits at most one new exit order per cycle in the first controlled
    phase. Runner/trailing exits remain preview-only until D.4.
    """
    ticker = _normalize_ticker(plan.get("ticker") or position.get("ticker"))
    position_id = str(plan.get("position_id") or _position_id(position) or "").strip()
    position_base = _position_base(position)
    reserved_base = _reserved_base_for_position(order_store, ticker=ticker, position_id=position_id)
    available_base = max(ZERO, position_base - reserved_base)
    max_quote = min(_cfg_dec(cfg, "phase_d3_max_exit_order_quote", D3_MAX_EXIT_QUOTE), D3_MAX_EXIT_QUOTE)
    increment = _base_increment(exchange_rules)
    min_quote = max(_min_order_quote(exchange_rules), _cfg_dec(cfg, "min_live_order_quote_usdc", Decimal("20.00")))
    price_increment = _price_increment(exchange_rules)

    warnings: List[str] = []
    blockers: List[str] = []
    if position_base <= ZERO:
        blockers.append("position_base_missing_or_zero")
    if available_base <= ZERO:
        blockers.append("no_available_base_after_existing_exit_reservations")
    risk_state = position_protective_risk_state(position, None)
    if not risk_state["complete"]:
        blockers.append("position_risk_incomplete_stop_or_invalidation_missing")

    selected: Optional[Dict[str, Any]] = None
    for raw in _as_list(plan.get("exits")):
        if not isinstance(raw, dict):
            continue
        if bool(raw.get("trailing_stop")):
            warnings.append(f"runner_or_trailing_exit_preview_only:{raw.get('label') or 'RUNNER'}")
            continue
        label = str(raw.get("label") or "TP").upper()
        price = _to_decimal(raw.get("limit_price"), "0")
        base = _to_decimal(raw.get("base_size"), "0")
        if base <= ZERO or price <= ZERO:
            warnings.append(f"exit_intent_ignored_missing_size_or_price:{label}")
            continue
        selected = dict(raw)
        selected["label"] = label
        break

    if selected is None:
        blockers.append("no_limit_tp_exit_intent_available_for_d3")
        selected = {"label": "NONE", "base_size": "0", "limit_price": "0", "fraction": "0"}

    if selected is not None:
        duplicate = _has_duplicate_exit_for_label(order_store, ticker=ticker, position_id=position_id, label=str(selected.get("label") or ""))
        if duplicate:
            blockers.append("duplicate_exit_label_already_open_for_position")

    raw_limit_price = _to_decimal(selected.get("limit_price"), "0")
    target_policy = build_exit_target_source_policy_report(
        cfg=cfg,
        position=position,
        market_context={
            "current_price": position.get("last_mid_price") or position.get("current_price"),
            "last_heartbeat_reason": position.get("last_heartbeat_reason"),
            "reasons": [position.get("last_heartbeat_reason"), position.get("last_position_risk_state")],
        },
        risk_reward_fallback_target=raw_limit_price,
    )
    if target_policy.get("is_stale_target"):
        blockers.append("exit_target_policy_stale_target")
        warnings.append(str(target_policy.get("target_reason") or "exit_target_policy_stale_target"))
    limit_price = _quantize_down(raw_limit_price, price_increment)
    if raw_limit_price > ZERO and limit_price <= ZERO:
        blockers.append("limit_price_quantized_to_zero")
    if raw_limit_price > ZERO and limit_price != raw_limit_price:
        warnings.append("limit_price_quantized_to_coinbase_increment")
    requested_base = min(_to_decimal(selected.get("base_size"), "0"), available_base)
    if limit_price > ZERO and requested_base * limit_price > max_quote:
        requested_base = max_quote / limit_price
        warnings.append("exit_base_clamped_to_phase_d3_max_quote")
    requested_base = _quantize_down(requested_base, increment)
    estimated_quote = requested_base * limit_price if limit_price > ZERO else ZERO
    label = str(selected.get("label") or "TP")
    quote_policy = validate_exit_quote_size(
        estimated_quote=estimated_quote,
        cfg=cfg,
        label=label,
        is_full_close=str(label).upper() == "TP_CLOSE",
        product_min_quote=min_quote,
    )
    blockers.extend(quote_policy["blockers"])
    warnings.extend(quote_policy["warnings"])
    if requested_base <= ZERO:
        blockers.append("sell_base_missing_or_zero_after_reservation_or_increment")

    cid = _client_order_id(ticker=ticker, position_id=position_id, label=str(selected.get("label") or "TP"))
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "intent_id": cid,
        "client_order_id": cid,
        "ticker": ticker,
        "position_id": position_id,
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "label": selected.get("label"),
        "size_base": str(requested_base),
        "raw_limit_price": str(raw_limit_price),
        "limit_price": str(limit_price),
        "estimated_quote_value": str(estimated_quote),
        "price_increment_used": str(price_increment),
        "price_precision_context": "exchange_rules_price_increment" if price_increment > ZERO else "no_price_increment_available",
        "requested_base_before_clamp": str(selected.get("base_size") or "0"),
        "position_base": str(position_base),
        "reserved_base_existing_exit_orders": str(reserved_base),
        "available_base_after_reservations": str(available_base),
        "reduce_only_local": True,
        "post_only": bool(getattr(cfg, "phase_d3_exit_order_post_only", True)),
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "live_order_size_policy": live_order_size_policy_report(cfg),
        "exit_quote_policy": quote_policy,
        "source_plan_id": str(plan.get("plan_id") or ""),
        "source_plan_status": str(plan.get("status") or ""),
        "exit_target_source_policy": target_policy,
        "protective_risk_state": risk_state,
    })


def build_phase_d3_exit_payload(*, cfg: Any, exit_intent: Dict[str, Any]) -> Dict[str, Any]:
    intent = _as_dict(exit_intent)
    base = _to_decimal(intent.get("size_base"), "0")
    limit_price = _to_decimal(intent.get("limit_price"), "0")
    raw_limit_price = _to_decimal(intent.get("raw_limit_price"), "0")
    ticker = _normalize_ticker(intent.get("ticker"))
    client_order_id = str(intent.get("client_order_id") or "").strip()
    reject_reasons: List[str] = []
    intent_blockers = sorted({str(blocker).strip() for blocker in _as_list(intent.get("blockers")) if str(blocker).strip()})
    if intent_blockers:
        reject_reasons.extend(f"exit_intent_blocked:{blocker}" for blocker in intent_blockers)
    if not client_order_id:
        reject_reasons.append("client_order_id_missing")
    if not ticker:
        reject_reasons.append("ticker_missing")
    if str(intent.get("side") or "").upper() != "SELL":
        reject_reasons.append("payload_requires_sell_side")
    if str(intent.get("execution_action") or "").lower() != "place_limit_sell":
        reject_reasons.append("payload_requires_place_limit_sell")
    if base <= ZERO:
        reject_reasons.append("base_size_missing_or_zero")
    if limit_price <= ZERO:
        reject_reasons.append("limit_price_missing_or_zero")

    payload = {
        "client_order_id": client_order_id,
        "product_id": ticker,
        "side": "SELL",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": format(base, "f"),
                "limit_price": format(limit_price, "f"),
                "post_only": bool(getattr(cfg, "phase_d3_exit_order_post_only", True)),
            }
        },
    }
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "ticker": ticker,
        "accepted": not reject_reasons,
        "reject_reasons": reject_reasons,
        "intent_blockers": intent_blockers,
        "client_order_id": client_order_id,
        "side": "SELL",
        "order_type": "limit_limit_gtc",
        "size_base": str(base),
        "raw_limit_price": str(raw_limit_price),
        "limit_price": str(limit_price),
        "estimated_quote_value": str(base * limit_price if base > ZERO and limit_price > ZERO else ZERO),
        "post_only": bool(getattr(cfg, "phase_d3_exit_order_post_only", True)),
        "price_increment_used": str(intent.get("price_increment_used") or "0"),
        "price_precision_context": str(intent.get("price_precision_context") or ""),
        "coinbase_payload_preview": payload,
        "safety_policy": {
            "reduce_only_local": True,
            "no_oversell_checked_before_submit": True,
            "coinbase_spot_has_no_native_reduce_only_flag": True,
        },
    })


def assess_phase_d3_exit_readiness(
    *,
    cfg: Any,
    position: Dict[str, Any],
    plan: Dict[str, Any],
    exit_intent: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    human_ack: str = "",
    submit_live: bool = False,
) -> Dict[str, Any]:
    ticker = _normalize_ticker(exit_intent.get("ticker") or position.get("ticker") or plan.get("ticker"))
    blockers: List[str] = []
    passed: List[str] = []
    warnings: List[str] = []
    allowed = {_normalize_ticker(x) for x in effective_phase_c_allowed_tickers(cfg) if _normalize_ticker(x)}
    position_base = _position_base(position)
    sell_base = _to_decimal(exit_intent.get("size_base"), "0")
    limit_price = _to_decimal(exit_intent.get("limit_price"), "0")
    estimated_quote = sell_base * limit_price if sell_base > ZERO and limit_price > ZERO else ZERO
    max_quote = min(_cfg_dec(cfg, "phase_d3_max_exit_order_quote", D3_MAX_EXIT_QUOTE), D3_MAX_EXIT_QUOTE)
    max_open = min(_cfg_int(cfg, "phase_d3_max_open_exit_orders", D3_MAX_OPEN_EXIT_ORDERS), D3_MAX_OPEN_EXIT_ORDERS)
    max_new = min(_cfg_int(cfg, "phase_d3_max_new_exit_orders_per_cycle", D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE), D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE)
    position_id = str(exit_intent.get("position_id") or plan.get("position_id") or _position_id(position) or "")
    open_d3_orders = _open_d3_exit_orders(order_store, ticker=ticker)
    reserved_base_this_position = _reserved_base_for_position(order_store, ticker=ticker, position_id=position_id)
    available_before_new = max(ZERO, position_base - reserved_base_this_position)

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(_cfg_bool(cfg, "enable_phase_d3_controlled_live_exits", True), "d3_controlled_live_exits_enabled", "d3_controlled_live_exits_disabled")
    require(is_d2_manageable_open_position(position, ticker=ticker), "position_manageable_open", "position_not_manageable_open")
    risk_state = position_protective_risk_state(position, None)
    require(bool(risk_state.get("complete")), "protective_risk_state_complete", "position_risk_incomplete_stop_or_invalidation_missing")
    require(str(plan.get("status") or "") == D2_PLAN_STATUS_READY, "d2_plan_ready", "d2_plan_not_ready")
    require(bool(ticker), "ticker_present", "ticker_missing")
    require((not allowed) or ticker in allowed, "ticker_allowed_or_allowlist_empty", "ticker_not_allowed")
    require(position_base > ZERO, "position_base_positive", "position_base_missing_or_zero")
    if _explicit_false(position.get("base_balance_verified")) or _explicit_false(position.get("current_base_balance_verified")):
        blockers.append("verified_base_balance_required_for_sell")
    else:
        passed.append("verified_base_balance_not_explicitly_false")
    require(sell_base > ZERO, "sell_base_positive", "sell_base_missing_or_zero")
    require(limit_price > ZERO, "limit_price_positive", "limit_price_missing_or_zero")
    require(sell_base <= available_before_new, "sell_base_lte_available_unreserved_base", "sell_base_exceeds_available_unreserved_base")
    require(estimated_quote > ZERO and estimated_quote <= max_quote, "estimated_quote_within_d3_cap", "estimated_quote_missing_or_above_d3_cap")
    intent_blockers = sorted({str(blocker).strip() for blocker in _as_list(exit_intent.get("blockers")) if str(blocker).strip()})
    if intent_blockers:
        blockers.extend(intent_blockers)
    require(str(exit_intent.get("side") or "").upper() == "SELL", "side_sell", "side_not_sell")
    require(str(exit_intent.get("execution_action") or "").lower() == "place_limit_sell", "execution_action_place_limit_sell", "execution_action_not_place_limit_sell")
    require(bool(exit_intent.get("reduce_only_local")), "reduce_only_local_true", "reduce_only_local_missing")
    require(len(open_d3_orders) < max_open, "open_exit_order_capacity_available", "max_open_d3_exit_orders_reached")
    require(max_new == 1, "max_one_new_exit_order_per_cycle", "phase_d3_max_new_exit_orders_per_cycle_must_be_1")
    require(
        not (order_store or OrderStore()).has_duplicate_exit_order(
            ticker=ticker,
            execution_action=str(exit_intent.get("execution_action") or ""),
            linked_position_id=position_id,
        ),
        "no_duplicate_open_exit_order_for_position_action",
        "duplicate_open_exit_order_for_position_action",
    )
    require("duplicate_exit_label_already_open_for_position" not in set(exit_intent.get("blockers") or []), "exit_label_not_already_open", "duplicate_exit_label_already_open_for_position")

    if str(exit_intent.get("label") or "").upper() not in {"TP1", "TP_CLOSE", "TP", "TP2"}:
        warnings.append("non_standard_exit_label_review_before_submit")
    if bool(exit_intent.get("trailing_stop")):
        blockers.append("trailing_runner_live_submit_deferred_to_d4")

    runtime_ack = str(getattr(cfg, "phase_d3_runtime_submit_ack", "") or "").strip()
    runtime_ack_valid = runtime_ack == D3_ACK
    caller_ack_valid = str(human_ack or "").strip() == D3_ACK
    caller_matches_runtime_ack = bool(runtime_ack and str(human_ack or "").strip() == runtime_ack)
    submit_armed = (
        _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False)
        and _cfg_bool(cfg, "enable_live_exit_orders", False)
        and _cfg_bool(cfg, "autonomous_allow_exits", False)
        and not _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True)
        and runtime_ack_valid
        and caller_ack_valid
        and caller_matches_runtime_ack
        and submit_live
    )
    if submit_live:
        require(_cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False), "phase_d3_actual_exit_submit_enabled", "phase_d3_actual_exit_submit_disabled")
        require(_cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_enabled", "live_exit_orders_disabled")
        require(_cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_allow_exits_enabled", "autonomous_allow_exits_disabled")
        require(not _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True), "phase_c_exit_disable_flag_released_for_d3", "phase_c_disable_exit_limit_orders_still_true")
        require(runtime_ack_valid, "runtime_ack_matches_d3", "phase_d3_runtime_submit_ack_missing_or_invalid")
        require(caller_ack_valid, "human_ack_matches_d3", "human_ack_missing_or_invalid")
        require(caller_matches_runtime_ack, "human_ack_matches_runtime_ack", "human_ack_not_equal_runtime_ack")
    else:
        passed.append("submit_live_argument_false_preview_only")

    ready = not blockers
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "ticker": ticker,
        "status": D3_READY_NO_SUBMIT if ready and not submit_armed else ("d3_controlled_exit_ready_for_live_submit" if ready and submit_armed else D3_BLOCKED),
        "ready": ready,
        "submit_armed": bool(submit_armed and ready),
        "blockers": sorted(set(blockers)),
        "passed_checks": sorted(set(passed)),
        "warnings": warnings,
        "position_base": str(position_base),
        "reserved_base_this_position": str(reserved_base_this_position),
        "available_base_before_new_exit": str(available_before_new),
        "sell_base": str(sell_base),
        "limit_price": str(limit_price),
        "estimated_quote_value": str(estimated_quote),
        "max_exit_quote": str(max_quote),
        "open_d3_exit_orders_count": len(open_d3_orders),
        "max_open_d3_exit_orders": int(max_open),
        "safety_policy": {
            "reduce_only_local": True,
            "max_one_new_exit_order_per_cycle": True,
            "max_120_usdc_per_exit_order": True,
            "no_oversell": True,
            "duplicate_exit_protection": True,
            "human_ack_required_for_live_submit": True,
            "runtime_operator_ack_required_for_live_submit": True,
        },
        "protective_risk_state": risk_state,
    })


def append_phase_d3_audit(event: Dict[str, Any], path: Path = D3_AUDIT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        import json
        fh.write(json.dumps(_json_safe({"generated_at": _now_iso(), **event}), sort_keys=True) + "\n")


def _submit_phase_d3_controlled_exit_unlocked(
    *,
    cfg: Any,
    position: Dict[str, Any],
    plan: Dict[str, Any],
    exit_intent: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    coinbase_client: Any = None,
    human_ack: str = "",
    submit_live: bool = False,
    audit_path: Path = D3_AUDIT_PATH,
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    readiness = assess_phase_d3_exit_readiness(
        cfg=cfg,
        position=position,
        plan=plan,
        exit_intent=exit_intent,
        order_store=store,
        human_ack=human_ack,
        submit_live=submit_live,
    )
    payload = build_phase_d3_exit_payload(cfg=cfg, exit_intent=exit_intent)
    result: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "ticker": _normalize_ticker(exit_intent.get("ticker")),
        "status": D3_READY_NO_SUBMIT if readiness.get("ready") else D3_BLOCKED,
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "readiness": readiness,
        "payload": payload,
        "local_order_record": None,
        "safety_policy": {
            "preview_when_submit_live_false": True,
            "actual_submit_requires_d3_flag_live_exit_flags_ack_and_client": True,
        },
    }

    hard_blocks: List[str] = []
    if not readiness.get("ready"):
        hard_blocks.append("d3_readiness_not_green")
    if not payload.get("accepted"):
        hard_blocks.append("d3_payload_not_accepted")
    if not readiness.get("submit_armed"):
        hard_blocks.append("d3_submit_not_armed")
    if coinbase_client is None:
        hard_blocks.append("coinbase_client_missing")
    result["hard_blocks"] = hard_blocks

    if not hard_blocks:
        result["live_submission_attempted"] = True
        try:
            gate = assert_live_exit_allowed(
                cfg=cfg,
                side="SELL",
                source_module="bot.phase_d3_controlled_live_exits",
                source_function="submit_phase_d3_controlled_exit",
                source_tag="phase_d3_controlled_live_exit",
                intended_exit_type="limit_sell",
                ticker=str(exit_intent.get("ticker") or ""),
                client_order_id=str(exit_intent.get("client_order_id") or ""),
                local_position_id=str(exit_intent.get("position_id") or plan.get("position_id") or ""),
                reason=str(exit_intent.get("label") or "D3_EXIT"),
                close_reason=str(exit_intent.get("label") or "D3_EXIT"),
                execution_status=D3_SUBMIT_ATTEMPTED,
                human_ack=human_ack,
                required_human_ack=D3_ACK,
            )
            preview = payload.get("coinbase_payload_preview") or {}
            gtc = ((preview.get("order_configuration") or {}).get("limit_limit_gtc") or {})
            response = coinbase_client.place_limit_order(
                ticker=str(preview.get("product_id") or exit_intent.get("ticker")),
                side="SELL",
                base_size=_to_decimal(gtc.get("base_size"), "0"),
                limit_price=_to_decimal(gtc.get("limit_price"), "0"),
                client_order_id=str(preview.get("client_order_id") or exit_intent.get("client_order_id")),
                post_only=bool(gtc.get("post_only", True)),
            )
            response_dict = _as_dict(_json_safe(response))
            response_success = bool(response_dict.get("success", True))
            error_response = _as_dict(response_dict.get("error_response"))
            order_id = str(
                response_dict.get("order_id")
                or response_dict.get("id")
                or (response_dict.get("success_response") or {}).get("order_id")
                or ""
            ).strip()
            if response_success and order_id:
                record = {
                    "client_order_id": str(exit_intent.get("client_order_id")),
                    "exchange_order_id": order_id,
                    "order_id": order_id,
                    "ticker": _normalize_ticker(exit_intent.get("ticker")),
                    "product_id": _normalize_ticker(exit_intent.get("ticker")),
                    "side": "SELL",
                    "status": "submitted",
                    "mode": "live",
                    "source_mode": "phase_d3_live_exit",
                    "phase": D3_PHASE,
                    "created_at": _now_iso(),
                    "size_base": str(exit_intent.get("size_base")),
                    "remaining_size": str(exit_intent.get("size_base")),
                    "size_quote": str(exit_intent.get("estimated_quote_value")),
                    "remaining_quote": "0",
                    "limit_price": str(exit_intent.get("limit_price")),
                    "post_only": bool(exit_intent.get("post_only", True)),
                    "execution_action": "place_limit_sell",
                    "linked_position_id": str(exit_intent.get("position_id") or plan.get("position_id") or ""),
                    "linked_trade_plan_id": str(plan.get("plan_id") or ""),
                    "reduce_only_local": True,
                    "d3_exit_label": str(exit_intent.get("label") or ""),
                    "coinbase_response": response_dict,
                }
                local_record = store.upsert_order(record, event_type="phase_d3_live_exit_order_submitted")
                lifecycle_event = build_lifecycle_order_event(
                    event_type="d3_live_exit_intent",
                    ticker=_normalize_ticker(exit_intent.get("ticker")),
                    order={
                        "product_id": _normalize_ticker(exit_intent.get("ticker")),
                        "side": "SELL",
                        "client_order_id": str(exit_intent.get("client_order_id")),
                        "exchange_order_id": order_id,
                        "limit_price": str(exit_intent.get("limit_price")),
                        "base_size": str(exit_intent.get("size_base")),
                        "linked_position_id": str(exit_intent.get("position_id") or plan.get("position_id") or ""),
                        "phase": "D3",
                    },
                    position={"position_id": str(exit_intent.get("position_id") or plan.get("position_id") or "")},
                    metadata={"source_phase": D3_PHASE, "linked_trade_plan_id": str(plan.get("plan_id") or "")},
                )
                lifecycle_publish_result = publish_lifecycle_event_best_effort(lifecycle_event)
                if isinstance(local_record, dict):
                    local_record = dict(local_record)
                    local_record["replication_lifecycle_publish_result"] = lifecycle_publish_result
                result.update({
                    "status": D3_SUBMITTED,
                    "live_order_submitted": True,
                    "live_exit_policy": gate,
                    "coinbase_response": response_dict,
                    "local_order_record": local_record,
                })
            else:
                reject_reason = (
                    "coinbase_success_without_order_id"
                    if response_success
                    else str(error_response.get("error") or "coinbase_submit_success_false")
                )
                reject_message = str(error_response.get("message") or "")
                preview_failure_reason = str(error_response.get("preview_failure_reason") or "")
                rejected_record = {
                    "client_order_id": str(exit_intent.get("client_order_id")),
                    "exchange_order_id": "",
                    "order_id": "",
                    "ticker": _normalize_ticker(exit_intent.get("ticker")),
                    "product_id": _normalize_ticker(exit_intent.get("ticker")),
                    "side": "SELL",
                    "status": "rejected",
                    "mode": "live",
                    "source_mode": "phase_d3_live_exit",
                    "phase": D3_PHASE,
                    "created_at": _now_iso(),
                    "size_base": str(exit_intent.get("size_base")),
                    "remaining_size": "0",
                    "size_quote": str(exit_intent.get("estimated_quote_value")),
                    "remaining_quote": "0",
                    "limit_price": str(exit_intent.get("limit_price")),
                    "post_only": bool(exit_intent.get("post_only", True)),
                    "execution_action": "place_limit_sell",
                    "linked_position_id": str(exit_intent.get("position_id") or plan.get("position_id") or ""),
                    "linked_trade_plan_id": str(plan.get("plan_id") or ""),
                    "reduce_only_local": True,
                    "d3_exit_label": str(exit_intent.get("label") or ""),
                    "rejected_at": _now_iso(),
                    "finalized_at": _now_iso(),
                    "closed_at": _now_iso(),
                    "reject_reason": reject_reason,
                    "coinbase_error_code": str(error_response.get("error") or ""),
                    "coinbase_error_message": reject_message,
                    "preview_failure_reason": preview_failure_reason,
                    "coinbase_response": response_dict,
                }
                result.update({
                    "status": D3_SUBMIT_REJECTED,
                    "live_order_submitted": False,
                    "live_exit_policy": gate,
                    "coinbase_response": response_dict,
                    "reject_reason": reject_reason,
                    "reject_message": reject_message,
                    "preview_failure_reason": preview_failure_reason,
                    "local_order_record": store.upsert_order(rejected_record, event_type="phase_d3_live_exit_order_rejected"),
                })
        except LiveExitBlockedError as exc:
            blocked_event = build_blocked_live_exit_event(
                exc.evaluation,
                execution_status="d3_controlled_live_exit_blocked_by_policy",
            )
            append_live_exit_event(blocked_event)
            result.update({
                "status": "d3_controlled_live_exit_blocked_by_policy",
                "live_order_submitted": False,
                "live_exit_policy": exc.evaluation,
                "blocked_exit_event": blocked_event,
                "hard_blocks": sorted(set((result.get("hard_blocks") or []) + ["d3_live_exit_blocked_by_central_policy"])),
            })
        except Exception as exc:
            result.update({
                "status": "d3_controlled_live_exit_submit_failed",
                "live_order_submitted": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    append_phase_d3_audit({"event_type": "phase_d3_controlled_exit_submit_evaluated", "result": result}, audit_path)
    return _json_safe(result)


def submit_phase_d3_controlled_exit(
    *,
    cfg: Any,
    position: Dict[str, Any],
    plan: Dict[str, Any],
    exit_intent: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    coinbase_client: Any = None,
    human_ack: str = "",
    submit_live: bool = False,
    audit_path: Path = D3_AUDIT_PATH,
) -> Dict[str, Any]:
    """Submit the sole D3 SELL boundary under the runtime mutation lock."""
    if not submit_live:
        return _submit_phase_d3_controlled_exit_unlocked(
            cfg=cfg,
            position=position,
            plan=plan,
            exit_intent=exit_intent,
            order_store=order_store,
            coinbase_client=coinbase_client,
            human_ack=human_ack,
            submit_live=False,
            audit_path=audit_path,
        )

    with process_lock(
        runtime_mutation_lock_path(cfg=cfg, order_store=order_store),
        allow_reentrant=True,
    ) as lock_info:
        result = _submit_phase_d3_controlled_exit_unlocked(
            cfg=cfg,
            position=position,
            plan=plan,
            exit_intent=exit_intent,
            order_store=order_store,
            coinbase_client=coinbase_client,
            human_ack=human_ack,
            submit_live=True,
            audit_path=audit_path,
        )
    result["mutation_lock"] = {
        "acquired": True,
        "reentrant": bool(lock_info.get("reentrant")),
    }
    return result


def _load_saved_plan_for_ticker(ticker: str, plans_path: Path) -> Optional[Dict[str, Any]]:
    data = load_position_executor_plans(plans_path)
    plans = _as_dict(data.get("plans"))
    plan = plans.get(_normalize_ticker(ticker))
    return dict(plan) if isinstance(plan, dict) else None


def build_phase_d3_controlled_live_exit_report(
    *,
    cfg: Any,
    ticker: str,
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
    coinbase_client: Any = None,
    position: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    submit_live: bool = False,
    human_ack: str = "",
    sample_position: bool = False,
    plans_path: Path = Path("state/phase_d2_position_executor_plans.json"),
    audit_path: Path = D3_AUDIT_PATH,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    store = state_store or StateStore()
    orders = order_store or OrderStore()
    pos = dict(position) if isinstance(position, dict) else None
    if pos is None and sample_position:
        pos = {
            "ticker": selected,
            "status": "open",
            "order_id": f"sample-d3-{selected}",
            "entry_price": "100.00",
            "position_size_base": "0.25",
            "position_size_quote": "25.00",
            "bot_managed_base": "0.25",
            "stop_price": "97.50",
        }
    if pos is None:
        raw = store.get_position(selected)
        pos = raw if is_d2_manageable_open_position(raw or {}, ticker=selected) else None

    d2_plan = dict(plan) if isinstance(plan, dict) else None
    d2_plan_source = "provided"
    if d2_plan is None:
        saved = _load_saved_plan_for_ticker(selected, plans_path)
        if saved and str(saved.get("status")) == D2_PLAN_STATUS_READY:
            d2_plan = saved
            d2_plan_source = "saved_state"
    if d2_plan is None and pos is not None:
        d2_report = build_phase_d2_position_executor_report(cfg=cfg, ticker=selected, state_store=store, position=pos, exchange_rules=exchange_rules, persist_plan=False)
        if isinstance(d2_report.get("plan"), dict):
            d2_plan = dict(d2_report["plan"])
            d2_plan_source = "fresh_d2_preview"
        else:
            d2_plan_source = "missing"

    base = {
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "ticker": selected,
        "status": D3_NO_PLAN,
        "enable_phase_d3_controlled_live_exits": _cfg_bool(cfg, "enable_phase_d3_controlled_live_exits", True),
        "enable_phase_d3_actual_exit_submit": _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False),
        "enable_live_exit_orders": _cfg_bool(cfg, "enable_live_exit_orders", False),
        "autonomous_allow_exits": _cfg_bool(cfg, "autonomous_allow_exits", False),
        "phase_c_disable_exit_limit_orders": _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True),
        "position_present": bool(pos),
        "plan_present": bool(d2_plan),
        "d2_plan_source": d2_plan_source,
        "open_d3_exit_orders": count_phase_d3_live_exit_orders(orders),
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "safety_policy": {
            "d3_submits_at_most_one_exit_order_per_cycle": True,
            "actual_submit_requires_explicit_submit_live_and_human_ack": True,
            "reduce_only_is_local_spot_invariant": True,
            "d2_plan_required": True,
            "d1_fill_reconciliation_remains_required_after_submit": True,
        },
    }
    base["reservation_governance"] = build_phase_d3_reservation_governance_snapshot(
        ticker=selected,
        position=pos,
        order_store=orders,
        plan=d2_plan,
        exchange_rules=exchange_rules,
    )

    if pos is None:
        base.update({"status": "d3_no_manageable_open_position", "blockers": ["no_manageable_open_position"], "next_step": "Wacht op een gevulde C.4.3 entry en D.2 plan."})
        return _json_safe(base)
    if not d2_plan or str(d2_plan.get("status")) != D2_PLAN_STATUS_READY:
        base.update({"status": D3_NO_PLAN, "blockers": ["d2_ready_plan_missing"], "plan": d2_plan, "next_step": "Maak eerst een D.2 position executor plan."})
        return _json_safe(base)

    exit_intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=d2_plan, position=pos, order_store=orders, exchange_rules=exchange_rules)
    result = submit_phase_d3_controlled_exit(
        cfg=cfg,
        position=pos,
        plan=d2_plan,
        exit_intent=exit_intent,
        order_store=orders,
        coinbase_client=coinbase_client,
        human_ack=human_ack,
        submit_live=submit_live,
        audit_path=audit_path,
    )
    base.update({
        "status": result.get("status"),
        "selected_exit_intent": exit_intent,
        "readiness": result.get("readiness"),
        "payload": result.get("payload"),
        "submit_result": result,
        "live_submission_attempted": bool(result.get("live_submission_attempted")),
        "live_order_submitted": bool(result.get("live_order_submitted")),
        "blockers": (result.get("readiness") or {}).get("blockers", []) + result.get("hard_blocks", []),
        "warnings": (result.get("readiness") or {}).get("warnings", []) + exit_intent.get("warnings", []),
        "next_step": "Na live submit: D.1/D.3 fill reconciliation monitoren; D.4 bouwt trailing/cancel-replace dynamiek.",
    })
    return _json_safe(base)


__all__ = [
    "D3_ACK",
    "D3_PHASE",
    "D3_SUBMIT_REJECTED",
    "assess_phase_d3_exit_readiness",
    "build_phase_d3_controlled_live_exit_report",
    "build_phase_d3_exit_payload",
    "build_phase_d3_full_close_exit_intent",
    "build_phase_d3_risk_close_exit_intent",
    "count_phase_d3_live_exit_orders",
    "select_next_phase_d3_exit_intent",
    "submit_phase_d3_controlled_exit",
]
