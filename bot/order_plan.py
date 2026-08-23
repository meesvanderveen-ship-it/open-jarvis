from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
import uuid

from bot.live_order_size_policy import validate_entry_quote_size, validate_exit_quote_size
from bot.dynamic_entry_sizing import calculate_dynamic_entry_quote
from bot.product_rules import canonical_product_rules, execution_feasibility_context


ORDER_ACTION_TO_SIDE_TYPE = {
    "place_limit_buy": ("BUY", "limit"),
    "place_limit_sell_reduce": ("SELL", "limit"),
    "place_limit_sell_close": ("SELL", "limit"),
}

ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS = set(ORDER_ACTION_TO_SIDE_TYPE.keys())


ZERO = Decimal("0")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def safe_float(value: Any) -> Optional[float]:
    dec = to_decimal(value, "0")
    if dec <= ZERO:
        return None
    return float(dec)


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _first_decimal(*values: Any, default: str = "0") -> Decimal:
    for value in values:
        dec = to_decimal(value, "0")
        if dec > ZERO:
            return dec
    return Decimal(default)


def _market_price_from_feature_pack(feature_pack: Dict[str, Any]) -> Decimal:
    market = feature_pack.get("market", {}) if isinstance(feature_pack.get("market"), dict) else {}
    orderbook_context = feature_pack.get("orderbook_context", {}) if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    return _first_decimal(
        market.get("mid_price"),
        orderbook_context.get("mid_price"),
        market.get("price"),
        market.get("last_price"),
        orderbook_context.get("best_ask"),
        orderbook_context.get("best_bid"),
    )


def _limit_price_from_orderbook(execution_action: str, orderbook_summary: Dict[str, Any]) -> Decimal:
    if not isinstance(orderbook_summary, dict):
        return ZERO
    if execution_action == "place_limit_buy":
        zones = orderbook_summary.get("passive_buy_zones") or []
        if isinstance(zones, list):
            for zone in zones:
                if isinstance(zone, dict):
                    price = to_decimal(zone.get("suggested_reference_price"), "0")
                    if price > ZERO:
                        return price
        return _first_decimal(orderbook_summary.get("best_bid"), orderbook_summary.get("mid_price"))
    if execution_action in {"place_limit_sell_reduce", "place_limit_sell_close"}:
        zones = orderbook_summary.get("passive_sell_zones") or []
        if isinstance(zones, list):
            for zone in zones:
                if isinstance(zone, dict):
                    price = to_decimal(zone.get("suggested_reference_price"), "0")
                    if price > ZERO:
                        return price
        return _first_decimal(orderbook_summary.get("best_ask"), orderbook_summary.get("mid_price"))
    return ZERO


def _limit_price_from_trade_plan(execution_action: str, trade_plan: Dict[str, Any]) -> Decimal:
    if not isinstance(trade_plan, dict):
        return ZERO
    if execution_action == "place_limit_buy":
        low = to_decimal(trade_plan.get("entry_zone_low"), "0")
        high = to_decimal(trade_plan.get("entry_zone_high"), "0")
        if low > ZERO and high > ZERO:
            return (low + high) / Decimal("2")
        return _first_decimal(trade_plan.get("entry_price"), trade_plan.get("trigger_level"), trade_plan.get("trigger_price"))
    if execution_action == "place_limit_sell_reduce":
        return _first_decimal(trade_plan.get("take_profit_1"), trade_plan.get("take_profit_price"))
    if execution_action == "place_limit_sell_close":
        return _first_decimal(trade_plan.get("take_profit_2"), trade_plan.get("take_profit_1"), trade_plan.get("take_profit_price"))
    return ZERO


def _limit_price_from_position_action(position_action: Optional[Dict[str, Any]], feature_pack: Dict[str, Any]) -> Decimal:
    if not isinstance(position_action, dict):
        return ZERO
    return _first_decimal(
        position_action.get("limit_price"),
        position_action.get("take_profit_price"),
        position_action.get("stop_price"),
        _market_price_from_feature_pack(feature_pack),
    )


def _do_not_chase_above(trade_plan: Dict[str, Any], limit_price: Decimal) -> Optional[str]:
    value = to_decimal((trade_plan or {}).get("do_not_chase_above"), "0")
    if value <= ZERO:
        return None
    return str(value)


def _invalidation_price(trade_plan: Dict[str, Any], position_action: Optional[Dict[str, Any]], execution_action: str) -> Optional[str]:
    if execution_action == "place_limit_buy":
        price = _first_decimal(
            (trade_plan or {}).get("stop_loss"),
            (trade_plan or {}).get("invalidation_price"),
            (trade_plan or {}).get("invalidation_level"),
        )
        return str(price) if price > ZERO else None
    if isinstance(position_action, dict):
        price = _first_decimal(position_action.get("stop_price"), position_action.get("invalidation_price"))
        return str(price) if price > ZERO else None
    price = _first_decimal((trade_plan or {}).get("stop_loss"), (trade_plan or {}).get("invalidation_price"))
    return str(price) if price > ZERO else None


def _size_for_order(
    *,
    execution_action: str,
    judge: Dict[str, Any],
    trade_plan: Optional[Dict[str, Any]] = None,
    position_action: Optional[Dict[str, Any]],
    existing_position: Optional[Dict[str, Any]],
    limit_price: Decimal,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    warnings: List[str] = []
    if execution_action == "place_limit_buy":
        plan = trade_plan if isinstance(trade_plan, dict) else {}
        quote = _first_decimal(
            judge.get("size_quote"),
            judge.get("quote_size"),
            plan.get("max_quote_size"),
            plan.get("max_size_quote"),
            plan.get("size_quote"),
        )
        if quote <= ZERO:
            warnings.append("missing_buy_quote_size_from_judge_or_trade_plan")
            return None, None, warnings
        base = quote / limit_price if limit_price > ZERO else ZERO
        return str(quote), str(base) if base > ZERO else None, warnings

    # Sell orders are local reduce-only paper simulations. Prefer explicit action size.
    action_size_base = _first_decimal((position_action or {}).get("size_base"), (judge or {}).get("size_base"))
    position_base = _first_decimal((existing_position or {}).get("position_size_base"), (existing_position or {}).get("size_base"))
    if execution_action == "place_limit_sell_close" and position_base > ZERO:
        action_size_base = position_base
    if action_size_base <= ZERO:
        warnings.append("missing_sell_base_size_from_position_or_action")
        return None, None, warnings
    if position_base > ZERO and action_size_base > position_base:
        warnings.append("paper_sell_size_clamped_to_existing_position_base")
        action_size_base = position_base
    quote = action_size_base * limit_price if limit_price > ZERO else ZERO
    return str(quote) if quote > ZERO else None, str(action_size_base), warnings


def _build_client_order_id(ticker: str, action: str) -> str:
    clean = normalize_ticker(ticker).replace("-", "")
    return f"paper-{clean}-{action.replace('_', '-')}-{uuid.uuid4().hex[:16]}"



class OrderPlan(dict):
    """Backward-compatible dict wrapper for paper order intents.

    Phase B uses functional helpers (build_order_intent_from_execution_plan and
    is_actionable_order_intent) internally. This lightweight wrapper exists so
    diagnostics, scripts, or future modules can import OrderPlan without
    changing the current workflow. It intentionally behaves like a normal dict
    and does not place, cancel, replace, or mutate live Coinbase orders.
    """

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]] = None) -> "OrderPlan":
        return cls(dict(data or {}))

    def to_dict(self) -> Dict[str, Any]:
        return dict(self)


class PaperOrderPlan(OrderPlan):
    """Alias-style subclass for future paper-order tooling."""



def build_order_intent_from_execution_plan(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    feature_pack: Dict[str, Any],
    existing_position: Optional[Dict[str, Any]] = None,
    position_action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize a read-only execution plan into a paper order intent.

    This function deliberately does not place live orders. It only prepares a
    validated intent that the phase-B paper manager can store and simulate.
    """
    ticker = normalize_ticker(ticker)
    analysis = analysis if isinstance(analysis, dict) else {}
    execution_plan = execution_plan if isinstance(execution_plan, dict) else {}
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    judge = analysis.get("judge", {}) if isinstance(analysis.get("judge"), dict) else {}
    trade_plan = analysis.get("trade_plan", {}) if isinstance(analysis.get("trade_plan"), dict) else {}
    orderbook_summary = execution_plan.get("orderbook_summary") if isinstance(execution_plan.get("orderbook_summary"), dict) else {}
    decision_context = feature_pack.get("decision_context", {}) if isinstance(feature_pack.get("decision_context"), dict) else {}
    product_rules = canonical_product_rules(
        ticker,
        decision_context.get("product_rules") or feature_pack.get("product_rules") or feature_pack.get("exchange_rules") or execution_plan.get("product_rules") or {},
    )

    action = str(execution_plan.get("execution_action") or "no_order").strip().lower()
    side, order_type = ORDER_ACTION_TO_SIDE_TYPE.get(action, ("NONE", "none"))
    warnings: List[str] = []
    reject_reasons: List[str] = []

    if action not in ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS:
        reject_reasons.append(f"execution_action_{action}_does_not_create_paper_order")

    limit_price = _limit_price_from_trade_plan(action, trade_plan)
    if limit_price <= ZERO:
        limit_price = _limit_price_from_position_action(position_action, feature_pack)
    if limit_price <= ZERO:
        limit_price = _limit_price_from_orderbook(action, orderbook_summary)
    if limit_price <= ZERO:
        limit_price = _market_price_from_feature_pack(feature_pack)
        if limit_price > ZERO:
            warnings.append("limit_price_fell_back_to_market_mid_context")

    if limit_price <= ZERO and action in ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS:
        reject_reasons.append("missing_concrete_limit_price")

    size_quote, size_base, size_warnings = _size_for_order(
        execution_action=action,
        judge=judge,
        trade_plan=trade_plan,
        position_action=position_action,
        existing_position=existing_position,
        limit_price=limit_price,
    )
    warnings.extend(size_warnings)
    dynamic_entry_sizing: Dict[str, Any] = {}
    if action == "place_limit_buy" and bool(getattr(cfg, "enable_dynamic_entry_sizing", False)):
        dynamic_entry_sizing = calculate_dynamic_entry_quote(
            cfg=cfg,
            analysis=analysis,
            execution_plan=execution_plan,
            product_rules=product_rules,
        )
        sized_quote = to_decimal(dynamic_entry_sizing.get("clamped_quote"), "0")
        size_quote = str(sized_quote) if sized_quote > ZERO else None
        size_base = str(sized_quote / limit_price) if sized_quote > ZERO and limit_price > ZERO else None
        if not bool(dynamic_entry_sizing.get("accepted")):
            reject_reasons.extend(
                f"dynamic_entry_sizing:{reason}"
                for reason in dynamic_entry_sizing.get("blockers") or []
            )
    if action in ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS:
        if side == "BUY" and to_decimal(size_quote, "0") <= ZERO:
            reject_reasons.append("missing_or_zero_buy_quote_size")
        if side == "BUY" and to_decimal(size_quote, "0") > ZERO:
            quote_policy = validate_entry_quote_size(size_quote, cfg)
            reject_reasons.extend(quote_policy["blockers"])
        if side == "SELL" and to_decimal(size_base, "0") <= ZERO:
            reject_reasons.append("missing_or_zero_sell_base_size")
        if side == "SELL" and to_decimal(size_quote, "0") > ZERO:
            exit_policy = validate_exit_quote_size(
                estimated_quote=size_quote,
                cfg=cfg,
                label="TP_CLOSE" if action == "place_limit_sell_close" else "PARTIAL",
                is_full_close=action == "place_limit_sell_close",
            )
            reject_reasons.extend(exit_policy["blockers"])
            warnings.extend(exit_policy["warnings"])

    expiry_hours = to_int(execution_plan.get("expiry_hours"), 0)
    if action in ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS and expiry_hours <= 0:
        reject_reasons.append("missing_positive_expiry_hours")

    created_at = now_utc()
    expires_at = created_at + timedelta(hours=max(0, expiry_hours))
    invalidation_price = _invalidation_price(trade_plan, position_action, action)
    if action == "place_limit_buy" and invalidation_price is None:
        reject_reasons.append("missing_invalidation_price_for_buy")

    do_not_chase = _do_not_chase_above(trade_plan, limit_price)
    if action == "place_limit_buy" and do_not_chase is not None and limit_price > to_decimal(do_not_chase, "0"):
        reject_reasons.append("limit_price_above_do_not_chase_above")
    execution_feasibility = {}
    if action == "place_limit_buy":
        execution_feasibility = execution_feasibility_context(
            ticker,
            size_quote,
            limit_price,
            product_rules,
            max_quote_size=getattr(cfg, "phase_c_max_order_quote", getattr(cfg, "autonomous_max_order_quote", "0")),
        )
        if not product_rules.get("precision_context_available"):
            reject_reasons.append("product_precision_context_missing")
        reject_reasons.extend([f"execution_feasibility:{b}" for b in execution_feasibility.get("blockers") or []])

    status = "planned" if not reject_reasons else "failed"
    return {
        "intent_id": f"intent-{uuid.uuid4().hex}",
        "ticker": ticker,
        "side": side,
        "order_type": order_type,
        "execution_action": action,
        "limit_price": str(limit_price) if limit_price > ZERO else None,
        "size_quote": size_quote,
        "size_base": size_base,
        "linked_trade_plan_id": trade_plan.get("plan_id") or trade_plan.get("trade_plan_id"),
        "linked_position_id": (existing_position or {}).get("position_id") or (existing_position or {}).get("id"),
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat() if expiry_hours > 0 else None,
        "invalidation_price": invalidation_price,
        "do_not_chase_above": do_not_chase,
        "cancel_if": list(execution_plan.get("cancel_if") or []),
        "replace_if": list(execution_plan.get("replace_if") or []),
        "coinbase_order_id": None,
        "client_order_id": _build_client_order_id(ticker, action),
        "status": status,
        "filled_size": "0",
        "remaining_size": size_base or "0",
        "avg_fill_price": None,
        "reason": execution_plan.get("reason") or "paper_order_intent_from_execution_plan",
        "product_rules": product_rules,
        "recent_exchange_rejections": decision_context.get("recent_exchange_rejections") or execution_plan.get("recent_exchange_rejections") or [],
        "execution_feasibility": execution_feasibility,
        "dynamic_entry_sizing": dynamic_entry_sizing,
        "gpt_output": execution_plan,
        "risk_check_result": {
            "mode": "paper_only_phase_b",
            "accepted": not reject_reasons,
            "reject_reasons": reject_reasons,
            "warnings": warnings,
            "deterministic_risk_rails_still_required_before_live_phase": True,
        },
        "paper_only": True,
        "live_order_submitted": False,
    }


def is_actionable_order_intent(intent: Dict[str, Any]) -> bool:
    if not isinstance(intent, dict):
        return False
    if str(intent.get("status", "")).lower() == "failed":
        return False
    if str(intent.get("execution_action", "")).lower() not in ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS:
        return False
    if to_decimal(intent.get("limit_price"), "0") <= ZERO:
        return False
    if str(intent.get("side", "")).upper() == "BUY" and to_decimal(intent.get("size_quote"), "0") <= ZERO:
        return False
    if str(intent.get("side", "")).upper() == "SELL" and to_decimal(intent.get("size_base"), "0") <= ZERO:
        return False
    if not intent.get("expires_at"):
        return False
    return True

__all__ = [
    "OrderPlan",
    "PaperOrderPlan",
    "ORDER_ACTION_TO_SIDE_TYPE",
    "ORDER_ACTIONS_THAT_CREATE_PAPER_ORDERS",
    "build_order_intent_from_execution_plan",
    "is_actionable_order_intent",
    "normalize_ticker",
    "safe_float",
    "to_decimal",
    "to_int",
]
