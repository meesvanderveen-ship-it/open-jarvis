from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


ZERO = Decimal("0")

# Canonical persisted-order status model. Unknown states remain reserved until
# terminal evidence exists: dropping a spot reservation on an unrecognised
# exchange response can permit a duplicate entry or oversell.
OPEN_ORDER_STATUSES = frozenset(
    {
        "planned",
        "pending",
        "submitted",
        "partially_filled",
        "cancel_pending",
        "replace_pending",
        "open",
        "active",
        "new",
        "queued",
        "unknown",
    }
)
FINAL_ORDER_STATUSES = frozenset(
    {
        "filled",
        "cancelled",
        "expired",
        "invalidated",
        "replaced",
        "failed",
        "rejected",
        "submit_rejected",
    }
)
_STATUS_ALIASES = {
    "accepted": "submitted",
    "canceled": "cancelled",
    "canceled_order": "cancelled",
    "cancelled_order": "cancelled",
    "complete": "filled",
    "completed": "filled",
    "done": "filled",
    "failure": "failed",
    "partial": "partially_filled",
    "pending_cancel": "cancel_pending",
    "settled": "filled",
    "timed_out": "expired",
    "timeout": "expired",
}


def normalize_order_status(value: Any, *, default: str = "unknown") -> str:
    """Map exchange/local aliases into one persisted lifecycle vocabulary."""
    status = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not status:
        return default
    return _STATUS_ALIASES.get(status, status)


def is_final_order_status(value: Any) -> bool:
    return normalize_order_status(value) in FINAL_ORDER_STATUSES


def is_open_order_status(value: Any) -> bool:
    """Treat every non-final order as reserved, including unknown statuses."""
    return not is_final_order_status(value)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _parse_iso(value: Any) -> Optional[datetime]:
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


def _market_context(feature_pack: Dict[str, Any]) -> Dict[str, Decimal]:
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    market = feature_pack.get("market", {}) if isinstance(feature_pack.get("market"), dict) else {}
    orderbook_context = feature_pack.get("orderbook_context", {}) if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    best_bid = _to_decimal(orderbook_context.get("best_bid") or market.get("best_bid"), "0")
    best_ask = _to_decimal(orderbook_context.get("best_ask") or market.get("best_ask"), "0")
    mid = _to_decimal(orderbook_context.get("mid_price") or market.get("mid_price") or market.get("price"), "0")
    if mid <= ZERO and best_bid > ZERO and best_ask > ZERO:
        mid = (best_bid + best_ask) / Decimal("2")
    return {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid}


def evaluate_paper_order_lifecycle(
    order: Dict[str, Any],
    feature_pack: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluate a paper order without touching Coinbase or live positions."""
    now = now or datetime.now(timezone.utc)
    status = normalize_order_status(order.get("status", "submitted"), default="submitted")
    if is_final_order_status(status):
        return {"action": "unchanged", "status": status, "reason": "order_already_final"}

    expires_at = _parse_iso(order.get("expires_at"))
    if expires_at is not None and now >= expires_at:
        return {"action": "expire", "status": "expired", "reason": "paper_order_expired"}

    ctx = _market_context(feature_pack)
    best_bid = ctx["best_bid"]
    best_ask = ctx["best_ask"]
    mid = ctx["mid_price"]
    limit_price = _to_decimal(order.get("limit_price"), "0")
    invalidation = _to_decimal(order.get("invalidation_price"), "0")
    side = str(order.get("side", "")).upper().strip()

    if side == "BUY" and invalidation > ZERO and mid > ZERO and mid <= invalidation:
        return {
            "action": "invalidate",
            "status": "invalidated",
            "reason": "paper_buy_invalidation_price_breached",
            "market_snapshot": {k: str(v) for k, v in ctx.items()},
        }

    if limit_price <= ZERO:
        return {"action": "fail", "status": "failed", "reason": "missing_limit_price_for_paper_lifecycle"}

    if side == "BUY":
        if best_ask > ZERO and best_ask <= limit_price:
            return {
                "action": "fill",
                "status": "filled",
                "reason": "paper_limit_buy_crossed_best_ask",
                "fill_price": str(best_ask),
                "market_snapshot": {k: str(v) for k, v in ctx.items()},
            }
        return {
            "action": "keep",
            "status": status if status else "submitted",
            "reason": "paper_limit_buy_not_filled_best_ask_above_limit",
            "market_snapshot": {k: str(v) for k, v in ctx.items()},
        }

    if side == "SELL":
        if best_bid > ZERO and best_bid >= limit_price:
            return {
                "action": "fill",
                "status": "filled",
                "reason": "paper_limit_sell_crossed_best_bid",
                "fill_price": str(best_bid),
                "market_snapshot": {k: str(v) for k, v in ctx.items()},
            }
        return {
            "action": "keep",
            "status": status if status else "submitted",
            "reason": "paper_limit_sell_not_filled_best_bid_below_limit",
            "market_snapshot": {k: str(v) for k, v in ctx.items()},
        }

    return {"action": "fail", "status": "failed", "reason": "unknown_order_side_for_paper_lifecycle"}
