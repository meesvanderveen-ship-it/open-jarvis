from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.product_rules import validate_limit_buy_payload


ZERO = Decimal("0")


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
        out = Decimal(text)
        if out.is_nan() or out.is_infinite():
            return Decimal(default)
        return out
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _cfg_decimal(cfg: Any, name: str, default: str = "0") -> Decimal:
    return _to_decimal(getattr(cfg, name, default), default)


def evaluate_amount_cap_guard(
    *,
    cfg: Any,
    ticker: str,
    requested_quote: Any,
    limit_price: Any,
    product_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate quote caps and quote-to-base conversion before live BUY submit."""
    quote = _to_decimal(requested_quote, "0")
    price = _to_decimal(limit_price, "0")
    phase_c_max = _cfg_decimal(cfg, "phase_c_max_order_quote", "0")
    autonomous_max = _cfg_decimal(cfg, "autonomous_max_order_quote", "0")
    max_notional = _cfg_decimal(cfg, "max_notional_usd", "0")
    blockers: List[str] = []
    passed: List[str] = []

    if quote <= ZERO:
        blockers.append("requested_quote_missing_or_zero")
    if phase_c_max > ZERO and quote > phase_c_max:
        blockers.append("requested_quote_above_phase_c_max_order_quote")
    else:
        passed.append("requested_quote_within_phase_c_max_order_quote")
    if autonomous_max > ZERO and quote > autonomous_max:
        blockers.append("requested_quote_above_autonomous_max_order_quote")
    else:
        passed.append("requested_quote_within_autonomous_max_order_quote")
    if max_notional > ZERO and quote > max_notional:
        blockers.append("requested_quote_above_max_notional_usd")
    else:
        passed.append("requested_quote_within_max_notional_usd")

    effective_max = min([x for x in (phase_c_max, autonomous_max, max_notional) if x > ZERO], default=ZERO)
    precision = validate_limit_buy_payload(
        ticker,
        quote,
        price,
        product_rules or {},
        max_quote_size=effective_max,
    )
    normalized_base = _to_decimal(precision.get("normalized_base_size"), "0")
    normalized_quote = _to_decimal(precision.get("normalized_quote_size"), "0")
    estimated_quote = _to_decimal(precision.get("estimated_quote_after_rounding"), "0")

    if "product_rules_missing" in precision.get("blockers", []):
        blockers.append("quote_to_base_conversion_missing_product_rules")
    if price <= ZERO:
        blockers.append("quote_to_base_conversion_missing_limit_price")
    if normalized_base <= ZERO:
        blockers.append("quote_to_base_conversion_missing")
    else:
        passed.append("quote_to_base_conversion_present")
    if price > Decimal("1") and quote > Decimal("1") and normalized_base == normalized_quote:
        blockers.append("base_size_appears_to_equal_quote_size_for_high_priced_asset")
    if precision.get("blockers"):
        blockers.extend([f"precision:{reason}" for reason in precision.get("blockers") or []])

    return {
        "generated_at": _now_iso(),
        "phase": "amount_cap_guard_v1",
        "ticker": str(ticker or "").upper(),
        "accepted": not blockers,
        "requested_quote": str(quote),
        "limit_price": str(price),
        "phase_c_max_order_quote": str(phase_c_max),
        "autonomous_max_order_quote": str(autonomous_max),
        "max_notional_usd": str(max_notional),
        "normalized_quote_size": str(normalized_quote),
        "normalized_base_size": str(normalized_base),
        "estimated_quote_after_rounding": str(estimated_quote),
        "blockers": sorted(set(blockers)),
        "passed_checks": sorted(set(passed)),
        "precision": precision,
        "safety_policy": {
            "quote_is_authoritative_cap": True,
            "base_size_must_derive_from_quote_and_price": True,
            "low_price_assets_may_have_base_numerically_above_quote": True,
        },
    }


__all__ = ["evaluate_amount_cap_guard"]
