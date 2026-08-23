from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple


ZERO = Decimal("0")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
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


def _level_price(level: Any) -> Decimal:
    if isinstance(level, dict):
        return _to_decimal(level.get("price"), "0")
    if isinstance(level, (list, tuple)) and level:
        return _to_decimal(level[0], "0")
    return ZERO


def _level_size(level: Any) -> Decimal:
    if isinstance(level, dict):
        return _to_decimal(level.get("size"), "0")
    if isinstance(level, (list, tuple)) and len(level) >= 2:
        return _to_decimal(level[1], "0")
    return ZERO


def _normalize_levels(levels: Any, *, side: str, max_levels: int = 25) -> List[Dict[str, str]]:
    if not isinstance(levels, list):
        return []
    normalized: List[Dict[str, str]] = []
    for level in levels[:max_levels]:
        price = _level_price(level)
        size = _level_size(level)
        if price <= ZERO or size <= ZERO:
            continue
        normalized.append({"price": str(price), "size": str(size), "side": side})
    return normalized


def _sum_size(levels: Iterable[Dict[str, str]], limit: int) -> Decimal:
    total = ZERO
    for level in list(levels)[:limit]:
        total += _to_decimal(level.get("size"), "0")
    return total


def _cluster_levels(levels: List[Dict[str, str]], *, side: str, max_clusters: int = 3) -> List[Dict[str, Any]]:
    if not levels:
        return []

    sizes = [_to_decimal(level.get("size"), "0") for level in levels]
    positive_sizes = [s for s in sizes if s > ZERO]
    if not positive_sizes:
        return []

    avg_size = sum(positive_sizes, ZERO) / Decimal(len(positive_sizes))
    if avg_size <= ZERO:
        return []

    clusters: List[Dict[str, Any]] = []
    for idx, level in enumerate(levels):
        price = _to_decimal(level.get("price"), "0")
        size = _to_decimal(level.get("size"), "0")
        if price <= ZERO or size <= ZERO:
            continue
        size_multiple = size / avg_size if avg_size > ZERO else ZERO
        if size_multiple < Decimal("1.35") and idx >= 5:
            continue
        clusters.append({
            "side": side,
            "level_index": idx,
            "price": str(price),
            "size": str(size),
            "size_multiple_vs_book_avg": float(size_multiple),
            "cluster_type": "liquidity_wall" if size_multiple >= Decimal("2.0") else "notable_cluster",
        })

    clusters.sort(key=lambda x: float(x.get("size_multiple_vs_book_avg", 0.0)), reverse=True)
    return clusters[:max_clusters]


def _nearest_level_distance_pct(reference: Decimal, target: Decimal) -> Optional[float]:
    if reference <= ZERO or target <= ZERO:
        return None
    return float((target - reference) / reference)


def build_orderbook_summary(
    feature_pack: Dict[str, Any],
    *,
    raw_orderbook: Optional[Dict[str, Any]] = None,
    max_levels: int = 25,
    stale_after_seconds: int = 900,
) -> Dict[str, Any]:
    """Build an objective, read-only orderbook summary for execution planning.

    The summary deliberately does not create buy/sell signals. It only describes
    top-of-book, depth, clusters, rough slippage and passive price zones so an
    execution planner can decide *how* to execute an already approved trade plan.
    """
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    market = feature_pack.get("market", {}) if isinstance(feature_pack.get("market"), dict) else {}
    orderbook_context = feature_pack.get("orderbook_context", {}) if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    indicators = feature_pack.get("indicators", {}) if isinstance(feature_pack.get("indicators"), dict) else {}
    structure = feature_pack.get("structure", {}) if isinstance(feature_pack.get("structure"), dict) else {}
    micro = feature_pack.get("microstructure", {}) if isinstance(feature_pack.get("microstructure"), dict) else {}

    raw_orderbook = raw_orderbook if isinstance(raw_orderbook, dict) else {}
    bids = _normalize_levels(raw_orderbook.get("bids"), side="bid", max_levels=max_levels)
    asks = _normalize_levels(raw_orderbook.get("asks"), side="ask", max_levels=max_levels)

    best_bid = _to_decimal(
        orderbook_context.get("best_bid")
        or orderbook_context.get("top_bid_price")
        or market.get("best_bid"),
        "0",
    )
    best_ask = _to_decimal(
        orderbook_context.get("best_ask")
        or orderbook_context.get("top_ask_price")
        or market.get("best_ask"),
        "0",
    )
    if best_bid <= ZERO and bids:
        best_bid = _to_decimal(bids[0].get("price"), "0")
    if best_ask <= ZERO and asks:
        best_ask = _to_decimal(asks[0].get("price"), "0")

    mid_price = _to_decimal(orderbook_context.get("mid_price") or market.get("mid_price"), "0")
    if mid_price <= ZERO and best_bid > ZERO and best_ask > ZERO:
        mid_price = (best_bid + best_ask) / Decimal("2")

    spread_abs = best_ask - best_bid if best_bid > ZERO and best_ask > ZERO else ZERO
    spread_pct = (spread_abs / best_ask) if best_ask > ZERO else ZERO

    bid_depth_top5 = _to_decimal(orderbook_context.get("bid_depth_top5"), "0")
    ask_depth_top5 = _to_decimal(orderbook_context.get("ask_depth_top5"), "0")
    if bids:
        bid_depth_top5 = _sum_size(bids, 5)
    if asks:
        ask_depth_top5 = _sum_size(asks, 5)

    depth_total = bid_depth_top5 + ask_depth_top5
    depth_imbalance = (bid_depth_top5 - ask_depth_top5) / depth_total if depth_total > ZERO else ZERO
    if depth_imbalance > Decimal("0.15"):
        book_pressure = "bid_heavy"
    elif depth_imbalance < Decimal("-0.15"):
        book_pressure = "ask_heavy"
    elif depth_total > ZERO:
        book_pressure = "balanced"
    else:
        book_pressure = str(orderbook_context.get("book_pressure", "unknown") or "unknown")

    snapshot_available = bool(orderbook_context.get("snapshot_available")) or bool(bids or asks)
    generated_at = _parse_iso_datetime(feature_pack.get("generated_at"))
    age_seconds = None
    freshness_status = "unknown"
    if generated_at is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - generated_at).total_seconds()))
        freshness_status = "fresh" if age_seconds <= stale_after_seconds else "stale"
    elif snapshot_available:
        freshness_status = "unknown"

    bid_clusters = _cluster_levels(bids, side="bid")
    ask_clusters = _cluster_levels(asks, side="ask")

    i1h = indicators.get("1h", {}) if isinstance(indicators.get("1h"), dict) else {}
    nearest_supports = [
        _to_decimal(i1h.get("donchian_20_low"), "0"),
        _to_decimal(i1h.get("bb_lower"), "0"),
        _to_decimal(structure.get("support_level_1h"), "0"),
    ]
    nearest_resistances = [
        _to_decimal(i1h.get("donchian_20_high"), "0"),
        _to_decimal(i1h.get("bb_upper"), "0"),
        _to_decimal(structure.get("resistance_level_1h"), "0"),
    ]
    nearest_supports = [x for x in nearest_supports if x > ZERO]
    nearest_resistances = [x for x in nearest_resistances if x > ZERO]

    passive_buy_zones: List[Dict[str, Any]] = []
    if best_bid > ZERO:
        passive_buy_zones.append({
            "zone_type": "top_bid_or_inside_spread",
            "suggested_reference_price": str(best_bid),
            "distance_from_mid_pct": _nearest_level_distance_pct(mid_price, best_bid),
            "reason": "top bid reference; only execution context, not trade approval",
        })
    for cluster in bid_clusters[:2]:
        price = _to_decimal(cluster.get("price"), "0")
        passive_buy_zones.append({
            "zone_type": cluster.get("cluster_type", "bid_cluster"),
            "suggested_reference_price": str(price),
            "distance_from_mid_pct": _nearest_level_distance_pct(mid_price, price),
            "reason": "notable bid liquidity cluster; verify against trade plan and do_not_chase_above",
        })

    passive_sell_zones: List[Dict[str, Any]] = []
    if best_ask > ZERO:
        passive_sell_zones.append({
            "zone_type": "top_ask_or_inside_spread",
            "suggested_reference_price": str(best_ask),
            "distance_from_mid_pct": _nearest_level_distance_pct(mid_price, best_ask),
            "reason": "top ask reference; only execution context, not sell permission",
        })
    for cluster in ask_clusters[:2]:
        price = _to_decimal(cluster.get("price"), "0")
        passive_sell_zones.append({
            "zone_type": cluster.get("cluster_type", "ask_cluster"),
            "suggested_reference_price": str(price),
            "distance_from_mid_pct": _nearest_level_distance_pct(mid_price, price),
            "reason": "notable ask liquidity cluster; useful for TP/reduce placement context",
        })

    volume_confirmation = {
        "15m_volume_vs_avg": _to_float((micro.get("15m", {}) if isinstance(micro.get("15m"), dict) else {}).get("volume_vs_avg"), 0.0),
        "1h_volume_vs_avg": _to_float((micro.get("1h", {}) if isinstance(micro.get("1h"), dict) else {}).get("volume_vs_avg"), 0.0),
    }

    slippage_estimate = {
        "quality": "unknown",
        "reason": "insufficient full depth for exact slippage estimate",
    }
    if snapshot_available and best_bid > ZERO and best_ask > ZERO:
        if spread_pct <= Decimal("0.0015") and depth_total > ZERO:
            quality = "low_estimated_slippage"
        elif spread_pct <= Decimal("0.0050"):
            quality = "medium_estimated_slippage"
        else:
            quality = "high_estimated_slippage"
        slippage_estimate = {
            "quality": quality,
            "spread_pct": float(spread_pct),
            "top5_depth_base": str(depth_total),
            "reason": "rough estimate from spread and top depth; not a guaranteed fill model",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker": str(feature_pack.get("ticker") or raw_orderbook.get("product_id") or "UNKNOWN"),
        "snapshot_available": snapshot_available,
        "freshness_status": freshness_status,
        "snapshot_age_seconds": age_seconds,
        "source": {
            "feature_pack_generated_at": feature_pack.get("generated_at"),
            "orderbook_source_path": orderbook_context.get("source_path") or raw_orderbook.get("source_path"),
            "depth_is_top_only": bool(orderbook_context.get("depth_is_top_only") or raw_orderbook.get("depth_is_top_only", False)),
        },
        "top_of_book": {
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "mid_price": str(mid_price),
            "spread_abs": str(spread_abs),
            "spread_pct": float(spread_pct),
        },
        "depth": {
            "bid_depth_top5_base": str(bid_depth_top5),
            "ask_depth_top5_base": str(ask_depth_top5),
            "depth_imbalance_top5": float(depth_imbalance),
            "book_pressure": book_pressure,
        },
        "clusters": {
            "bid_clusters": bid_clusters,
            "ask_clusters": ask_clusters,
            "cluster_persistence": "unknown_in_phase_a_single_snapshot",
            "wall_stability": "unknown_in_phase_a_single_snapshot",
        },
        "technical_level_overlap": {
            "nearest_supports": [str(x) for x in nearest_supports[:5]],
            "nearest_resistances": [str(x) for x in nearest_resistances[:5]],
            "range_position": structure.get("range_position"),
        },
        "volume_confirmation": volume_confirmation,
        "slippage_estimate": slippage_estimate,
        "passive_buy_zones": passive_buy_zones[:4],
        "passive_sell_zones": passive_sell_zones[:4],
        "policy_note": "Orderbook data is execution context only; it must not create trade permission by itself.",
    }
