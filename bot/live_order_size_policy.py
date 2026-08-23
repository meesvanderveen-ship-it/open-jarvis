from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

from bot.governance_constants import MODE_C_MARKET_ORDER_ACK_VALUE


# New live entries are deliberately fee-efficient.  Exit caps are separate so
# a filled 100-USDC entry can still be closed completely after price movement.
MIN_LIVE_ORDER_QUOTE_USDC = Decimal("50.00")
MAX_LIVE_ORDER_QUOTE_USDC = Decimal("100.00")
MAX_LIVE_EXIT_ORDER_QUOTE_USDC = Decimal("120.00")
EXPLORATION_MIN_ORDER_QUOTE_USDC = Decimal("20.00")
EXPLORATION_MAX_ORDER_QUOTE_USDC = Decimal("35.00")


def to_decimal(value: Any, default: str = "0") -> Decimal:
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


def min_live_order_quote(cfg: Any = None) -> Decimal:
    return to_decimal(getattr(cfg, "min_live_order_quote_usdc", MIN_LIVE_ORDER_QUOTE_USDC), str(MIN_LIVE_ORDER_QUOTE_USDC))


def max_live_order_quote(cfg: Any = None) -> Decimal:
    return to_decimal(getattr(cfg, "max_live_order_quote_usdc", MAX_LIVE_ORDER_QUOTE_USDC), str(MAX_LIVE_ORDER_QUOTE_USDC))


def effective_exit_min_quote(cfg: Any = None, product_min_quote: Any = None) -> Decimal:
    return max(min_live_order_quote(cfg), to_decimal(product_min_quote, "0"))


def max_live_exit_quote(cfg: Any = None, *, label: Any = "") -> Decimal:
    """Return the explicitly separate D3/controlled-stop close capacity."""
    label_text = str(label or "").strip().upper()
    attr = "controlled_stop_exit_max_quote_usd" if label_text in {"STOP_EXIT", "CONTROLLED_STOP_EXIT", "RISK_CLOSE"} else "phase_d3_max_exit_order_quote"
    configured = to_decimal(getattr(cfg, attr, MAX_LIVE_EXIT_ORDER_QUOTE_USDC), str(MAX_LIVE_EXIT_ORDER_QUOTE_USDC))
    return min(configured, MAX_LIVE_EXIT_ORDER_QUOTE_USDC)


def validate_entry_quote_size(quote: Any, cfg: Any = None) -> Dict[str, Any]:
    value = to_decimal(quote, "0")
    min_quote = min_live_order_quote(cfg)
    max_quote = max_live_order_quote(cfg)
    blockers: List[str] = []
    if value <= Decimal("0"):
        blockers.append("missing_or_zero_quote_size")
    elif value < min_quote:
        blockers.append("quote_size_below_min_live_order_quote")
    elif value > max_quote:
        blockers.append("quote_size_above_max_live_order_quote")
    return {
        "accepted": not blockers,
        "quote_size": str(value),
        "min_quote_usdc": str(min_quote),
        "max_quote_usdc": str(max_quote),
        "blockers": blockers,
    }


def is_full_close_label(label: Any) -> bool:
    return str(label or "").strip().upper() in {
        "TP_CLOSE",
        "RISK_CLOSE",
        "STOP_EXIT",
        "CONTROLLED_STOP_EXIT",
        "FULL_CLOSE",
    }


def validate_exit_quote_size(
    *,
    estimated_quote: Any,
    cfg: Any = None,
    label: Any = "",
    is_full_close: bool = False,
    product_min_quote: Any = None,
) -> Dict[str, Any]:
    value = to_decimal(estimated_quote, "0")
    min_quote = effective_exit_min_quote(cfg, product_min_quote)
    max_quote = max_live_exit_quote(cfg, label=label)
    full_close = bool(is_full_close or is_full_close_label(label))
    blockers: List[str] = []
    warnings: List[str] = []
    if value <= Decimal("0"):
        blockers.append("exit_quote_missing_or_zero")
    elif value < min_quote and not full_close:
        blockers.append("exit_quote_below_min_live_order_quote")
    elif value < min_quote and full_close:
        warnings.append("full_close_below_min_live_order_quote_allowed")
    elif value > max_quote:
        blockers.append("exit_quote_above_max_live_order_quote")
    return {
        "accepted": not blockers,
        "estimated_quote": str(value),
        "min_quote_usdc": str(min_quote),
        "max_quote_usdc": str(max_quote),
        "full_close_exception": full_close,
        "blockers": blockers,
        "warnings": warnings,
    }


def mode_c_market_orders_allowed(cfg: Any = None) -> bool:
    if cfg is None:
        return False
    market_flags_enabled = bool(
        getattr(cfg, "market_order_enabled", False)
        and getattr(cfg, "enable_market_orders", False)
        and getattr(cfg, "allow_market_orders", False)
    )
    ack_valid = str(getattr(cfg, "mode_c_market_order_ack", "") or "").strip() == MODE_C_MARKET_ORDER_ACK_VALUE
    replication_enabled = bool(
        getattr(cfg, "replication_enabled", False)
        or getattr(cfg, "replication_lifecycle_enabled", False)
        or getattr(cfg, "replication_lifecycle_http_enabled", False)
    )
    return bool(market_flags_enabled and ack_valid and not replication_enabled)


def live_order_size_policy_report(cfg: Any = None) -> Dict[str, Any]:
    return {
        "min_quote_usdc": str(min_live_order_quote(cfg)),
        "max_quote_usdc": str(max_live_order_quote(cfg)),
        "max_exit_quote_usdc": str(max_live_exit_quote(cfg)),
        "entry_under_min_blocked": True,
        "entry_above_max_blocked": True,
        "partial_exit_under_min_blocked": True,
        "full_close_exception_allowed": True,
        "market_orders_allowed": mode_c_market_orders_allowed(cfg),
    }


def bounded_exploration_report(cfg: Any = None) -> Dict[str, Any]:
    enabled = bool(getattr(cfg, "enable_bounded_exploration_mode", False)) if cfg is not None else False
    min_quote = to_decimal(getattr(cfg, "exploration_min_order_quote_usdc", EXPLORATION_MIN_ORDER_QUOTE_USDC), str(EXPLORATION_MIN_ORDER_QUOTE_USDC))
    max_quote = to_decimal(getattr(cfg, "exploration_max_order_quote_usdc", EXPLORATION_MAX_ORDER_QUOTE_USDC), str(EXPLORATION_MAX_ORDER_QUOTE_USDC))
    market_orders = bool(getattr(cfg, "exploration_allow_market_orders", False)) if cfg is not None else False
    explicit_allowed = list(getattr(cfg, "exploration_allowed_tickers", []) or []) if cfg is not None else []
    configured_allowed = []
    if cfg is not None:
        for attr in ("allowed_tickers", "phase_c_allowed_tickers", "autonomous_allowed_tickers"):
            for ticker in list(getattr(cfg, attr, []) or []):
                ticker_text = str(ticker or "").strip().upper().replace("/", "-")
                if ticker_text and ticker_text not in configured_allowed:
                    configured_allowed.append(ticker_text)
    allowed_tickers = explicit_allowed or configured_allowed
    blockers: List[str] = []
    if enabled and market_orders:
        blockers.append("bounded_exploration_market_orders_enabled")
    if enabled and min_quote < MIN_LIVE_ORDER_QUOTE_USDC:
        blockers.append("bounded_exploration_min_quote_below_20")
    if enabled and max_quote > EXPLORATION_MAX_ORDER_QUOTE_USDC:
        blockers.append("bounded_exploration_max_quote_above_35")
    if enabled and min_quote > max_quote:
        blockers.append("bounded_exploration_min_quote_above_max")
    return {
        "enabled": enabled,
        "ready": not blockers,
        "min_quote_usdc": str(min_quote),
        "max_quote_usdc": str(max_quote),
        "max_open_probes": int(getattr(cfg, "exploration_max_open_probes", 1)) if cfg is not None else 1,
        "max_probes_per_day": int(getattr(cfg, "exploration_max_probes_per_day", 2)) if cfg is not None else 2,
        "allowed_tickers": allowed_tickers,
        "market_orders_allowed": market_orders,
        "requires_fresh_trigger": bool(getattr(cfg, "exploration_require_fresh_trigger", True)) if cfg is not None else True,
        "requires_hard_risk_green": bool(getattr(cfg, "exploration_require_hard_risk_green", True)) if cfg is not None else True,
        "requires_no_chase": bool(getattr(cfg, "exploration_require_no_chase", True)) if cfg is not None else True,
        "max_spread_pct": str(getattr(cfg, "exploration_max_spread_pct", "0.0040")) if cfg is not None else "0.0040",
        "requires_orderbook_snapshot": bool(getattr(cfg, "exploration_require_orderbook_snapshot", True)) if cfg is not None else True,
        "blockers": blockers,
    }


__all__ = [
    "EXPLORATION_MAX_ORDER_QUOTE_USDC",
    "EXPLORATION_MIN_ORDER_QUOTE_USDC",
    "MAX_LIVE_ORDER_QUOTE_USDC",
    "MAX_LIVE_EXIT_ORDER_QUOTE_USDC",
    "MIN_LIVE_ORDER_QUOTE_USDC",
    "bounded_exploration_report",
    "effective_exit_min_quote",
    "is_full_close_label",
    "live_order_size_policy_report",
    "max_live_order_quote",
    "max_live_exit_quote",
    "min_live_order_quote",
    "mode_c_market_orders_allowed",
    "to_decimal",
    "validate_entry_quote_size",
    "validate_exit_quote_size",
]
