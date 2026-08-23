from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional

ZERO = Decimal("0")
PRODUCT_RULE_NORMALIZER_VERSION = "product-rules-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_decimal(value: Any, default: str = "0") -> Decimal:
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


def normalize_product_id(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _first_positive(rules: Dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        dec = to_decimal(rules.get(key), "0")
        if dec > ZERO:
            return dec
    return ZERO


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    if increment <= ZERO:
        return value
    try:
        return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment
    except Exception:
        return value


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def canonical_product_rules(product_id: str, rules: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = rules if isinstance(rules, dict) else {}
    product = normalize_product_id(raw.get("product_id") or product_id)
    price_increment = _first_positive(raw, "price_increment", "price_increment_size")
    # Coinbase product payloads often expose quote_increment but not price_increment.
    # For limit prices, quote increment is the conservative fallback used elsewhere
    # in this repo when price_increment is absent.
    if price_increment <= ZERO:
        price_increment = _first_positive(raw, "quote_increment", "quote_increment_size")
    base_increment = _first_positive(raw, "base_increment", "base_increment_size")
    quote_increment = _first_positive(raw, "quote_increment", "quote_increment_size")
    min_base_size = _first_positive(raw, "base_min_size", "base_min_order_size", "min_order_size")
    min_quote_size = _first_positive(raw, "quote_min_size", "quote_min_order_size", "min_market_funds", "min_notional", "min_order_quote")
    max_quote_size = _first_positive(raw, "quote_max_size", "quote_max_order_size", "max_market_funds", "max_quote_size")
    max_base_size = _first_positive(raw, "base_max_size", "base_max_order_size", "max_order_size")
    return {
        "product_id": product,
        "price_increment": _fmt(price_increment),
        "base_increment": _fmt(base_increment),
        "quote_increment": _fmt(quote_increment),
        "min_base_size": _fmt(min_base_size),
        "max_base_size": _fmt(max_base_size),
        "min_quote_size": _fmt(min_quote_size),
        "max_quote_size": _fmt(max_quote_size),
        "precision_context_available": bool(price_increment > ZERO and base_increment > ZERO),
        "raw_rules_present": bool(raw),
    }


def normalize_price(product_id: str, price: Any, rules: Optional[Dict[str, Any]]) -> Decimal:
    canonical = canonical_product_rules(product_id, rules)
    return _quantize_down(to_decimal(price, "0"), to_decimal(canonical["price_increment"], "0"))


def normalize_base_size(product_id: str, base_size: Any, rules: Optional[Dict[str, Any]]) -> Decimal:
    canonical = canonical_product_rules(product_id, rules)
    return _quantize_down(to_decimal(base_size, "0"), to_decimal(canonical["base_increment"], "0"))


def normalize_quote_size(product_id: str, quote_size: Any, rules: Optional[Dict[str, Any]]) -> Decimal:
    canonical = canonical_product_rules(product_id, rules)
    return _quantize_down(to_decimal(quote_size, "0"), to_decimal(canonical["quote_increment"], "0"))


def quote_to_base_size(product_id: str, quote_size: Any, limit_price: Any, rules: Optional[Dict[str, Any]]) -> Decimal:
    price = normalize_price(product_id, limit_price, rules)
    quote = normalize_quote_size(product_id, quote_size, rules)
    if quote <= ZERO or price <= ZERO:
        return ZERO
    return normalize_base_size(product_id, quote / price, rules)


def validate_limit_buy_payload(
    product_id: str,
    quote_size: Any,
    limit_price: Any,
    rules: Optional[Dict[str, Any]],
    *,
    max_quote_size: Any = None,
) -> Dict[str, Any]:
    product = normalize_product_id(product_id)
    canonical = canonical_product_rules(product, rules)
    blockers: List[str] = []
    warnings: List[str] = []
    raw_quote = to_decimal(quote_size, "0")
    raw_price = to_decimal(limit_price, "0")
    price_increment = to_decimal(canonical["price_increment"], "0")
    base_increment = to_decimal(canonical["base_increment"], "0")
    quote_increment = to_decimal(canonical["quote_increment"], "0")
    min_base = to_decimal(canonical["min_base_size"], "0")
    min_quote = to_decimal(canonical["min_quote_size"], "0")
    product_max_quote = to_decimal(canonical["max_quote_size"], "0")
    cfg_max_quote = to_decimal(max_quote_size, "0") if max_quote_size is not None else ZERO
    effective_max_quote = min([x for x in (product_max_quote, cfg_max_quote) if x > ZERO], default=ZERO)

    if not canonical["raw_rules_present"]:
        blockers.append("product_rules_missing")
    if price_increment <= ZERO:
        blockers.append("price_increment_missing")
    if base_increment <= ZERO:
        blockers.append("base_increment_missing")
    if quote_increment <= ZERO:
        warnings.append("quote_increment_missing_quote_left_unrounded")
    if raw_quote <= ZERO:
        blockers.append("quote_size_missing_or_zero")
    if raw_price <= ZERO:
        blockers.append("limit_price_missing_or_zero")

    normalized_quote = normalize_quote_size(product, raw_quote, canonical)
    normalized_price = normalize_price(product, raw_price, canonical)
    raw_base = (normalized_quote / normalized_price) if normalized_quote > ZERO and normalized_price > ZERO else ZERO
    normalized_base = normalize_base_size(product, raw_base, canonical)
    estimated_quote = normalized_base * normalized_price if normalized_base > ZERO and normalized_price > ZERO else ZERO

    if raw_price > ZERO and normalized_price != raw_price:
        warnings.append("limit_price_rounded_down_to_price_increment")
    if raw_base > ZERO and normalized_base != raw_base:
        warnings.append("base_size_rounded_down_to_base_increment")
    if raw_quote > ZERO and normalized_quote != raw_quote:
        warnings.append("quote_size_rounded_down_to_quote_increment")
    if normalized_quote <= ZERO:
        blockers.append("quote_size_rounded_to_zero")
    if normalized_price <= ZERO:
        blockers.append("limit_price_rounded_to_zero")
    if normalized_base <= ZERO:
        blockers.append("base_size_rounded_to_zero")
    if min_quote > ZERO and estimated_quote < min_quote:
        blockers.append("estimated_quote_below_product_min_quote_size")
    if min_base > ZERO and normalized_base < min_base:
        blockers.append("base_size_below_product_min_base_size")
    if effective_max_quote > ZERO and estimated_quote > effective_max_quote:
        blockers.append("estimated_quote_above_max_quote_size")
    if raw_quote > ZERO and raw_quote > Decimal("1") and normalized_base == raw_quote:
        blockers.append("base_size_equals_quote_size_possible_quote_base_confusion")

    return {
        "generated_at": _now_iso(),
        "product_id": product,
        "quote_size": _fmt(raw_quote),
        "normalized_quote_size": _fmt(normalized_quote),
        "raw_limit_price": _fmt(raw_price),
        "normalized_limit_price": _fmt(normalized_price),
        "raw_base_size": _fmt(raw_base),
        "normalized_base_size": _fmt(normalized_base),
        "estimated_quote_after_rounding": _fmt(estimated_quote),
        **canonical,
        "effective_max_quote_size": _fmt(effective_max_quote),
        "valid": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def execution_feasibility_context(
    product_id: str,
    quote_size: Any,
    limit_price: Any,
    rules: Optional[Dict[str, Any]],
    *,
    max_quote_size: Any = None,
) -> Dict[str, Any]:
    report = validate_limit_buy_payload(product_id, quote_size, limit_price, rules, max_quote_size=max_quote_size)
    return {
        "can_construct_valid_limit_buy_payload": bool(report.get("valid")),
        "normalized_price": report.get("normalized_limit_price"),
        "normalized_base_size": report.get("normalized_base_size"),
        "estimated_quote": report.get("estimated_quote_after_rounding"),
        "blockers": list(report.get("blockers") or []),
        "warnings": list(report.get("warnings") or []),
    }


def explain_precision_adjustment(
    product_id: str,
    quote_size: Any,
    limit_price: Any,
    rules: Optional[Dict[str, Any]],
    *,
    max_quote_size: Any = None,
) -> Dict[str, Any]:
    return validate_limit_buy_payload(product_id, quote_size, limit_price, rules, max_quote_size=max_quote_size)


def load_product_rules_cache(path: str | Path = "reports/audits/per-ticker-product-rule-evidence-cache-latest.json") -> Dict[str, Dict[str, Any]]:
    requested = Path(path)
    candidate_paths = [requested]
    if str(requested) == "reports/audits/per-ticker-product-rule-evidence-cache-latest.json":
        candidate_paths.extend(
            [
                Path("reports/d6/per-ticker-product-rule-evidence-cache-20260609.json"),
                Path("reports/d6/product-rule-fixture-evidence-20260609.json"),
            ]
        )
    cache_path = next((candidate for candidate in candidate_paths if candidate.exists()), requested)
    if not cache_path.exists():
        return {}
    try:
        payload = __import__("json").loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = (
        payload.get("rules_by_ticker")
        or payload.get("product_rules")
        or payload.get("tickers")
        or payload.get("per_ticker_matrix")
        or payload.get("per_ticker_fixture_evidence_matrix")
        or payload
    )
    if isinstance(rows, list):
        rows = {
            str(row.get("ticker") or row.get("product_id") or "").strip().upper(): row
            for row in rows
            if isinstance(row, dict) and str(row.get("ticker") or row.get("product_id") or "").strip()
        }
    if not isinstance(rows, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in rows.items():
        if isinstance(value, dict):
            out[normalize_product_id(key)] = value
    return out


__all__ = [
    "PRODUCT_RULE_NORMALIZER_VERSION",
    "canonical_product_rules",
    "execution_feasibility_context",
    "explain_precision_adjustment",
    "load_product_rules_cache",
    "normalize_base_size",
    "normalize_price",
    "normalize_product_id",
    "normalize_quote_size",
    "quote_to_base_size",
    "to_decimal",
    "validate_limit_buy_payload",
]
