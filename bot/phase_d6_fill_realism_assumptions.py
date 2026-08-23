from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, decimal_str, now_iso, to_decimal


D6_FILL_REALISM_ASSUMPTIONS_PHASE = "D6_fill_realism_post_only_assumption_pack_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
    }


def _load_json_or_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    safe_path = assert_research_path(path)
    text = safe_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if safe_path.suffix.lower() == ".jsonl":
        return [row for row in (json.loads(line) for line in text.splitlines()) if isinstance(row, dict)]
    loaded = json.loads(text)
    if isinstance(loaded, list):
        return [row for row in loaded if isinstance(row, dict)]
    if isinstance(loaded, dict):
        for key in ("orders", "rows", "candidates", "evidence_rows", "events", "fill_realism_rows"):
            nested = loaded.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        return [loaded]
    return []


def _first(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _pct_distance(numerator: Any, denominator: Any) -> Optional[str]:
    base = to_decimal(denominator)
    if base == 0:
        return None
    return decimal_str((to_decimal(numerator) - base) / base)


def _spread_pct(bid: Any, ask: Any) -> Optional[str]:
    bid_dec = to_decimal(bid)
    ask_dec = to_decimal(ask)
    mid = (bid_dec + ask_dec) / to_decimal("2")
    if bid_dec <= 0 or ask_dec <= 0 or mid <= 0:
        return None
    return decimal_str((ask_dec - bid_dec) / mid)


def _side(row: Dict[str, Any]) -> str:
    return str(_first(row, ["side", "order_side"]) or "UNKNOWN").upper()


def _limit_price(row: Dict[str, Any]) -> Any:
    return _first(row, ["limit_price", "price", "planned_exit_price", "metric_value"])


def _base_size(row: Dict[str, Any]) -> Any:
    return _first(row, ["base_size", "size", "remaining_size", "planned_size_base", "filled_base"])


def _notional(limit_price: Any, base_size: Any) -> Optional[str]:
    price = to_decimal(limit_price)
    base = to_decimal(base_size)
    if price <= 0 or base <= 0:
        return None
    return decimal_str(price * base)


def _fee_impact(notional: Optional[str], maker_fee_pct: Any) -> Optional[str]:
    if notional is None:
        return None
    return decimal_str(to_decimal(notional) * to_decimal(maker_fee_pct))


def _crossing_risk(*, side: str, limit_price: Any, bid: Any, ask: Any) -> str:
    price = to_decimal(limit_price)
    bid_dec = to_decimal(bid)
    ask_dec = to_decimal(ask)
    if price <= 0 or bid_dec <= 0 or ask_dec <= 0:
        return "unknown_no_orderbook_context"
    if side == "SELL" and price <= bid_dec:
        return "crossing_or_taker_risk"
    if side == "BUY" and price >= ask_dec:
        return "crossing_or_taker_risk"
    return "post_only_non_crossing"


def _fill_class(*, side: str, limit_price: Any, bid: Any, ask: Any, notional: Optional[str]) -> str:
    price = to_decimal(limit_price)
    bid_dec = to_decimal(bid)
    ask_dec = to_decimal(ask)
    if notional is not None and to_decimal(notional) > 0 and to_decimal(notional) < to_decimal("10"):
        return "tiny_notional_high_overhead"
    if price <= 0 or bid_dec <= 0 or ask_dec <= 0:
        return "insufficient_orderbook_context"
    if _crossing_risk(side=side, limit_price=limit_price, bid=bid, ask=ask) == "crossing_or_taker_risk":
        return "crossing_or_taker_risk"
    reference = ask_dec if side == "SELL" else bid_dec
    distance = abs((price - reference) / reference) if reference > 0 else to_decimal("0")
    if distance >= to_decimal("0.02"):
        return "likely_unfillable_far_from_market"
    return "plausible_maker_near_market"


def _categories(fill_class: str, row: Dict[str, Any]) -> List[str]:
    categories = ["post_only_fill_behavior", "spread_distance_context"]
    text = json.dumps(row, sort_keys=True, default=str).lower()
    if fill_class in {"plausible_maker_near_market", "likely_unfillable_far_from_market"}:
        categories.append("fill_probability_context")
    if fill_class == "crossing_or_taker_risk":
        categories.append("maker_taker_liquidity")
    if fill_class == "tiny_notional_high_overhead":
        categories.append("tiny_notional_lifecycle_overhead")
    if row.get("no_fill_duration_seconds") not in (None, "") or "no_fill" in text:
        categories.append("no_fill_duration")
    if row.get("cancel_replace_count") not in (None, "") or "cancel_replace" in text or "reprice" in text:
        categories.append("cancel_replace_churn")
    if row.get("fee_quote") not in (None, "") or row.get("estimated_fee_impact") not in (None, ""):
        categories.append("cost_fill_realism_interaction")
    if "maker" in text or "taker" in text or "post_only" in text:
        categories.append("maker_taker_liquidity")
    return sorted(set(categories))


def _parameter_categories(categories: Iterable[str]) -> List[str]:
    mapped: set[str] = set()
    for category in categories:
        if category in {"post_only_fill_behavior", "cancel_replace_churn"}:
            mapped.add("d4_dynamic_order_management")
        if category in {"tiny_notional_lifecycle_overhead"}:
            mapped.add("d3_controlled_exit")
        if category in {"fill_probability_context", "no_fill_duration", "maker_taker_liquidity"}:
            mapped.add("d5_execution_learning")
        if category in {"cost_fill_realism_interaction"}:
            mapped.add("d2_position_executor")
        if category in {"spread_distance_context"}:
            mapped.add("market_data_features")
    return sorted(mapped or {"d5_execution_learning"})


def _evidence_strength(fill_class: str, bid: Any, ask: Any, row: Dict[str, Any]) -> str:
    if to_decimal(bid) <= 0 or to_decimal(ask) <= 0:
        return "insufficient"
    if row.get("is_complete_lifecycle_event") is True or row.get("fill_count") not in (None, ""):
        return "medium"
    if fill_class in {"crossing_or_taker_risk", "likely_unfillable_far_from_market"}:
        return "medium"
    return "weak"


def _warnings(fill_class: str) -> List[str]:
    warnings = [
        "fill_realism_assumption_only",
        "not_fill_probability_model",
        "not_parameter_recommendation",
        "not_live_order_instruction",
    ]
    if fill_class == "insufficient_orderbook_context":
        warnings.append("missing_orderbook_context")
    if fill_class == "tiny_notional_high_overhead":
        warnings.append("tiny_notional_requires_manual_review")
    return sorted(set(warnings))


def _blockers(row: Dict[str, Any]) -> List[str]:
    blockers = []
    if row.get("contains_rankings") is True:
        blockers.append("source_contains_rankings")
    if row.get("contains_recommendations") is True:
        blockers.append("source_contains_recommendations")
    text = json.dumps(row, sort_keys=True, default=str).lower()
    if "place order" in text or "submit_order" in text or "cancel_order" in text:
        blockers.append("source_may_contain_live_instruction_language")
    return sorted(set(blockers))


def build_fill_realism_rows(
    records: Iterable[Dict[str, Any]],
    *,
    maker_fee_pct: Any = "0.004",
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        side = _side(record)
        limit_price = _limit_price(record)
        bid = _first(record, ["reference_bid", "best_bid", "bid"])
        ask = _first(record, ["reference_ask", "best_ask", "ask"])
        base_size = _base_size(record)
        notional = _notional(limit_price, base_size)
        fill_class = _fill_class(side=side, limit_price=limit_price, bid=bid, ask=ask, notional=notional)
        categories = _categories(fill_class, record)
        rows.append(
            {
                "row_index": index,
                "product_id": str(_first(record, ["product_id", "ticker", "product"]) or "UNKNOWN"),
                "order_label": _first(record, ["order_label", "label", "exit_label"]),
                "side": side,
                "limit_price": str(limit_price) if limit_price is not None else None,
                "reference_bid": str(bid) if bid is not None else None,
                "reference_ask": str(ask) if ask is not None else None,
                "spread_pct": _spread_pct(bid, ask),
                "distance_to_best_bid_pct": _pct_distance(limit_price, bid) if bid is not None else None,
                "distance_to_best_ask_pct": _pct_distance(limit_price, ask) if ask is not None else None,
                "post_only_crossing_risk": _crossing_risk(side=side, limit_price=limit_price, bid=bid, ask=ask),
                "likely_maker": _crossing_risk(side=side, limit_price=limit_price, bid=bid, ask=ask) == "post_only_non_crossing",
                "tiny_notional_flag": notional is not None and to_decimal(notional) > 0 and to_decimal(notional) < to_decimal("10"),
                "notional_at_limit": notional,
                "estimated_fee_impact": _fee_impact(notional, maker_fee_pct),
                "no_fill_duration_seconds": _first(record, ["no_fill_duration_seconds", "stale_order_age_seconds"]),
                "cancel_replace_count": _first(record, ["cancel_replace_count", "replace_count", "reprice_count"]),
                "regime_labels": list(record.get("regime_labels") or []),
                "evidence_categories": categories,
                "parameter_categories_implicated": _parameter_categories(categories),
                "fill_realism_class": fill_class,
                "evidence_strength": _evidence_strength(fill_class, bid, ask, record),
                "warnings": _warnings(fill_class),
                "blockers": _blockers(record),
                "contains_live_signal": False,
                "parameter_change_allowed": False,
                "parameter_review_approved": False,
            }
        )
    return rows


def _count(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def build_phase_d6_fill_realism_assumption_report(
    *,
    input_paths: Iterable[str | Path],
    maker_fee_pct: Any = "0.004",
) -> Dict[str, Any]:
    paths = [assert_research_path(path) for path in input_paths]
    if not paths:
        raise ValueError("d6_fill_realism_requires_at_least_one_input_path")
    source_summary = []
    records: List[Dict[str, Any]] = []
    for path in paths:
        source_rows = _load_json_or_jsonl(path)
        source_summary.append({"source_file": str(path), "record_count": len(source_rows)})
        records.extend(source_rows)
    rows = build_fill_realism_rows(records, maker_fee_pct=maker_fee_pct)
    warnings = _count(warning for row in rows for warning in row.get("warnings") or [])
    blockers = _count(blocker for row in rows for blocker in row.get("blockers") or [])
    return {
        "generated_at": now_iso(),
        "phase": D6_FILL_REALISM_ASSUMPTIONS_PHASE,
        "status": "d6_fill_realism_assumption_report_ready",
        "source_summary": source_summary,
        "order_candidate_count": len(records),
        "fill_realism_rows": rows,
        "aggregate_summary": {
            "fill_realism_class_counts": _count(row.get("fill_realism_class") for row in rows),
            "evidence_category_counts": _count(category for row in rows for category in row.get("evidence_categories") or []),
            "parameter_category_counts": _count(category for row in rows for category in row.get("parameter_categories_implicated") or []),
            "evidence_strength_counts": _count(row.get("evidence_strength") for row in rows),
            "tiny_notional_count": sum(1 for row in rows if row.get("tiny_notional_flag") is True),
            "crossing_risk_count": sum(1 for row in rows if row.get("post_only_crossing_risk") == "crossing_or_taker_risk"),
        },
        "warning_counts": warnings,
        "blocker_counts": blockers,
        "warnings": [
            "fill_realism_assumption_pack_only",
            "not_parameter_review",
            "not_parameter_search",
            "not_optimization",
            "not_live_execution_model",
        ],
        "blockers": sorted(blockers),
        **_safety_flags(),
    }


__all__ = [
    "D6_FILL_REALISM_ASSUMPTIONS_PHASE",
    "build_fill_realism_rows",
    "build_phase_d6_fill_realism_assumption_report",
]
