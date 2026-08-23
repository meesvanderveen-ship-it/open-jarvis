from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, List, Optional

PHASE_C45_MAKER_SCOUT_PHASE = "C4.5_maker_price_scout"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _first_positive(*values: Any, default: str = "0") -> Decimal:
    for value in values:
        dec = _to_decimal(value, "0")
        if dec > 0:
            return dec
    return Decimal(default)


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    if increment <= 0:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def _levels_from_book(book: Dict[str, Any], side: str) -> List[Dict[str, str]]:
    levels = book.get(side) if isinstance(book, dict) else []
    if not isinstance(levels, list):
        return []
    out: List[Dict[str, str]] = []
    for level in levels:
        if isinstance(level, dict):
            price = str(level.get("price") or "0")
            size = str(level.get("size") or "0")
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = str(level[0])
            size = str(level[1])
        else:
            continue
        if _to_decimal(price) > 0:
            out.append({"price": price, "size": size})
    return out


def _product_increment(product: Dict[str, Any]) -> Decimal:
    # Coinbase spot products expose quote_increment for BTC-USDC price precision.
    # Some variants expose price_increment; accept both to keep the tool forward-safe.
    return _first_positive(
        product.get("price_increment"),
        product.get("price_increment_size"),
        product.get("quote_increment"),
        product.get("quote_increment_size"),
        default="0.01",
    )


def _product_quote_min(product: Dict[str, Any]) -> Decimal:
    return _first_positive(product.get("quote_min_size"), product.get("min_market_funds"), default="0")


def build_phase_c45_maker_price_scout_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    coinbase_client: Any = None,
    quote_size: Any = "10.00",
    join_best_bid: bool = True,
    bid_ticks_below: int = 0,
    max_spread_pct: Any = "0.20",
) -> Dict[str, Any]:
    """Read-only helper for choosing an explicit C.4.5 maker BUY price.

    The tool does not place, cancel or modify orders. It only reads Coinbase
    product/orderbook data and returns a concrete numeric limit_price for the
    existing C.4.3 one-entry pilot runner. It exists to prevent placeholder
    mistakes and obvious post-only crossing mistakes during live fill pilots.
    """
    selected = _normalize_ticker(ticker)
    blockers: List[str] = []
    warnings: List[str] = []
    passed_checks: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed_checks.append(ok)
        else:
            blockers.append(bad)

    require(not bool(getattr(cfg, "replication_enabled", False)), "replication_disabled", "replication_enabled_review_required")
    require(not bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)), "entry_actual_submit_disabled", "entry_actual_submit_still_enabled")
    require(not bool(getattr(cfg, "enable_live_exit_orders", False)), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(not bool(getattr(cfg, "autonomous_allow_exits", False)), "autonomous_exits_disabled", "autonomous_allow_exits_enabled_forbidden")
    require(not bool(getattr(cfg, "enable_phase_d3_actual_exit_submit", False)), "d3_actual_exit_submit_disabled", "d3_actual_exit_submit_enabled_forbidden")
    require(coinbase_client is not None, "coinbase_client_available", "coinbase_client_missing")

    book: Dict[str, Any] = {}
    product: Dict[str, Any] = {}
    if coinbase_client is not None:
        try:
            product = coinbase_client.get_product(selected)
        except Exception as exc:
            blockers.append("coinbase_product_read_failed")
            warnings.append(f"product_error:{type(exc).__name__}:{exc}")
        try:
            book = coinbase_client.get_product_book(selected, limit=5)
        except Exception as exc:
            blockers.append("coinbase_orderbook_read_failed")
            warnings.append(f"orderbook_error:{type(exc).__name__}:{exc}")

    bids = _levels_from_book(book, "bids")
    asks = _levels_from_book(book, "asks")
    best_bid = _to_decimal(bids[0].get("price") if bids else "0")
    best_ask = _to_decimal(asks[0].get("price") if asks else "0")
    increment = _product_increment(product)
    quote = _to_decimal(quote_size, "0")
    quote_min = _product_quote_min(product)
    ticks_below = max(0, int(bid_ticks_below or 0))
    max_spread = _to_decimal(max_spread_pct, "0.20")

    require(selected != "", "ticker_selected", "ticker_missing")
    require(quote > 0, "quote_size_positive", "quote_size_not_positive")
    if quote_min > 0:
        require(quote >= quote_min, "quote_size_above_product_min", "quote_size_below_product_min")
    require(best_bid > 0 and best_ask > 0, "top_of_book_available", "top_of_book_missing")
    require(increment > 0, "price_increment_available", "price_increment_missing")
    require(best_bid < best_ask, "positive_bid_ask_spread", "bid_ask_spread_invalid_or_crossed")

    spread_abs = best_ask - best_bid if best_bid > 0 and best_ask > 0 else Decimal("0")
    spread_pct = (spread_abs / best_ask * Decimal("100")) if best_ask > 0 else Decimal("0")
    if max_spread > 0:
        require(spread_pct <= max_spread, "spread_within_max", "spread_too_wide_for_fill_pilot")

    reference = best_bid if join_best_bid else (best_bid - increment)
    candidate = reference - (increment * Decimal(ticks_below))
    candidate = _quantize_down(candidate, increment)

    require(candidate > 0, "candidate_price_positive", "candidate_price_not_positive")
    require(candidate < best_ask, "candidate_price_below_best_ask_post_only_safe", "candidate_price_crosses_or_touches_best_ask")

    estimated_base = _quantize_down((quote / candidate), _first_positive(product.get("base_increment"), product.get("base_increment_size"), default="0.00000001")) if candidate > 0 else Decimal("0")
    distance_from_bid_abs = best_bid - candidate if best_bid > 0 and candidate > 0 else Decimal("0")
    distance_from_bid_pct = (distance_from_bid_abs / best_bid * Decimal("100")) if best_bid > 0 else Decimal("0")

    status = "maker_price_ready" if not blockers else "blocked_review_required"
    command_price = format(candidate, "f") if candidate > 0 else ""

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": PHASE_C45_MAKER_SCOUT_PHASE,
        "status": status,
        "ticker": selected,
        "quote_size": str(quote),
        "product_rules": {
            "base_increment": str(product.get("base_increment") or product.get("base_increment_size") or ""),
            "quote_increment": str(product.get("quote_increment") or product.get("quote_increment_size") or ""),
            "price_increment_used": str(increment),
            "quote_min_size": str(product.get("quote_min_size") or ""),
        },
        "top_of_book": {
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "spread_abs": str(spread_abs),
            "spread_pct": str(spread_pct),
            "book_time": book.get("time"),
            "book_source_path": book.get("source_path"),
            "depth_is_top_only": bool(book.get("depth_is_top_only", False)),
            "bids_top": bids[:3],
            "asks_top": asks[:3],
        },
        "maker_price": {
            "limit_price": command_price,
            "join_best_bid": bool(join_best_bid),
            "bid_ticks_below": ticks_below,
            "estimated_base_size": str(estimated_base),
            "distance_from_best_bid_abs": str(distance_from_bid_abs),
            "distance_from_best_bid_pct": str(distance_from_bid_pct),
            "post_only_buy_rule": "limit_price must remain below best_ask; best_bid/join-bid is intended as maker, but book can move before submit.",
        },
        "commands": {
            "preview": (
                "python3 tools/run_phase_c43_controlled_entry_pilot.py "
                f"--ticker {selected} --quote-size {quote} --limit-price {command_price} --json"
            ) if command_price else "",
            "submit_live": (
                "python3 tools/run_phase_c43_controlled_entry_pilot.py "
                f"--ticker {selected} --quote-size {quote} --limit-price {command_price} "
                "--submit-live --human-go-ack I_UNDERSTAND_AND_APPROVE_C43_CONTROLLED_ENTRY_PILOT --json"
            ) if command_price else "",
            "post_submit_disable_actual_submit_check": "grep -E '^(ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT|REPLICATION_ENABLED|ENABLE_LIVE_EXIT_ORDERS|AUTONOMOUS_ALLOW_EXITS|ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT)=' .env",
            "c45_read_only_poll": f"python3 tools/run_phase_c45_live_fill_pilot.py --ticker {selected} --allow-coinbase-poll --json",
        },
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed_checks,
        "safety_policy": {
            "read_only_coinbase_market_data": True,
            "does_not_place_entry_orders": True,
            "does_not_cancel_or_replace_orders": True,
            "does_not_apply_local_lifecycle": True,
            "does_not_build_d2_or_d3": True,
            "never_submits_live_sell_orders": True,
            "prevents_literal_placeholder_price": True,
        },
        "next_step": "Use the numeric maker_price.limit_price immediately for exactly one C.4.3 controlled entry pilot, then set actual submit false and run C.4.5 read-only poll. Re-scout if more than a few seconds pass or the book moves.",
    })


__all__ = ["PHASE_C45_MAKER_SCOUT_PHASE", "build_phase_c45_maker_price_scout_report"]
