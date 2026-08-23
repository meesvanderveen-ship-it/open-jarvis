from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, decimal_str, now_iso, to_decimal


D6_REGIME_SEGMENTATION_PHASE = "D6_regime_segmentation_scaffold_v1"
DEFAULT_WINDOW_SIZE = 20
DEFAULT_STEP_SIZE = 20


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_approved": False,
        "parameter_review_allowed": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def load_candles(path: str | Path) -> List[Dict[str, Any]]:
    safe_path = assert_research_path(path)
    loaded = json.loads(safe_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        loaded = loaded.get("candles") or loaded.get("rows") or []
    if not isinstance(loaded, list):
        raise ValueError("d6_regime_segmentation_requires_candle_list")
    return [row for row in loaded if isinstance(row, dict)]


def _required_fields_present(candle: Dict[str, Any]) -> bool:
    return all(key in candle for key in ("start", "open", "high", "low", "close", "volume"))


def _validate_candles(candles: List[Dict[str, Any]]) -> List[str]:
    blockers = []
    if not candles:
        blockers.append("empty_candle_dataset")
    if candles and any(not _required_fields_present(row) for row in candles):
        blockers.append("missing_required_candle_fields")
    return blockers


def _dec(value: Any) -> Decimal:
    return to_decimal(value)


def _pct_change(first: Decimal, last: Decimal) -> Decimal:
    if first == 0:
        return Decimal("0")
    return (last - first) / first


def _mean(values: Iterable[Decimal]) -> Decimal:
    vals = list(values)
    if not vals:
        return Decimal("0")
    return sum(vals, Decimal("0")) / Decimal(len(vals))


def _window_metrics(window: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    closes = [_dec(row.get("close")) for row in window]
    highs = [_dec(row.get("high")) for row in window]
    lows = [_dec(row.get("low")) for row in window]
    returns = []
    for prev, current in zip(closes, closes[1:]):
        if prev != 0:
            returns.append(abs((current - prev) / prev))
    total_return = _pct_change(closes[0], closes[-1]) if closes else Decimal("0")
    range_pct = Decimal("0")
    if closes and closes[-1] != 0:
        range_pct = (max(highs) - min(lows)) / closes[-1]
    return {
        "window_return": total_return,
        "avg_abs_return": _mean(returns),
        "range_pct": range_pct,
        "trend_slope_proxy": total_return / Decimal(max(len(window) - 1, 1)),
    }


def _labels(metrics: Dict[str, Decimal]) -> List[str]:
    labels: List[str] = []
    if metrics["avg_abs_return"] >= Decimal("0.025") or metrics["range_pct"] >= Decimal("0.18"):
        labels.append("high_volatility")
    elif metrics["avg_abs_return"] <= Decimal("0.005") and metrics["range_pct"] <= Decimal("0.05"):
        labels.append("low_volatility")
    if metrics["range_pct"] <= Decimal("0.04"):
        labels.append("compression")
    if metrics["window_return"] >= Decimal("0.04"):
        labels.append("uptrend")
    elif metrics["window_return"] <= Decimal("-0.04"):
        labels.append("downtrend")
    else:
        labels.append("range")
    if abs(metrics["window_return"]) >= Decimal("0.08") and metrics["range_pct"] >= Decimal("0.08"):
        labels.append("breakout_context")
    return sorted(set(labels))


def _count_labels(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        for label in row.get("regime_labels") or []:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def build_phase_d6_regime_segmentation_report(
    *,
    candle_path: str | Path,
    window_size: int = DEFAULT_WINDOW_SIZE,
    step_size: int = DEFAULT_STEP_SIZE,
) -> Dict[str, Any]:
    if int(window_size) <= 1:
        raise ValueError("d6_regime_window_size_must_be_greater_than_one")
    if int(step_size) <= 0:
        raise ValueError("d6_regime_step_size_must_be_positive")

    path = assert_research_path(candle_path)
    candles = sorted(load_candles(path), key=lambda row: int(row.get("start") or 0))
    blockers = _validate_candles(candles)
    warnings = [
        "regime_segmentation_scaffold_only",
        "not_strategy_signal",
        "not_parameter_search",
        "not_parameter_recommendation",
    ]
    rows: List[Dict[str, Any]] = []
    if not blockers and len(candles) < int(window_size):
        blockers.append("insufficient_candles_for_window")

    if not blockers:
        for start_index in range(0, len(candles) - int(window_size) + 1, int(step_size)):
            window = candles[start_index : start_index + int(window_size)]
            metrics = _window_metrics(window)
            labels = _labels(metrics)
            rows.append(
                {
                    "window_index": len(rows),
                    "start_index": start_index,
                    "end_index": start_index + int(window_size) - 1,
                    "first_candle_start": window[0].get("start"),
                    "last_candle_start": window[-1].get("start"),
                    "regime_labels": labels,
                    "window_return": decimal_str(metrics["window_return"]),
                    "avg_abs_return": decimal_str(metrics["avg_abs_return"]),
                    "range_pct": decimal_str(metrics["range_pct"]),
                    "trend_slope_proxy": decimal_str(metrics["trend_slope_proxy"]),
                    "contains_live_signal": False,
                    "parameter_change_allowed": False,
                }
            )

    product_id = str(candles[0].get("product_id") or candles[0].get("ticker") or "UNKNOWN") if candles else "UNKNOWN"
    timeframe = str(candles[0].get("timeframe") or "UNKNOWN") if candles else "UNKNOWN"
    if blockers:
        warnings.append("regime_dataset_not_usable_without_fix")
    return {
        "generated_at": now_iso(),
        "phase": D6_REGIME_SEGMENTATION_PHASE,
        "status": "d6_regime_segmentation_ready" if not blockers else "d6_regime_segmentation_blocked",
        "source_file": str(path),
        "product_id": product_id,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "first_candle_start": candles[0].get("start") if candles else None,
        "last_candle_start": candles[-1].get("start") if candles else None,
        "window_size": int(window_size),
        "step_size": int(step_size),
        "regime_window_count": len(rows),
        "regime_counts": _count_labels(rows),
        "window_rows": rows,
        "warnings": warnings,
        "blockers": sorted(set(blockers)),
        "usable_for_future_research": not blockers and bool(rows),
        **_safety_flags(),
    }


__all__ = [
    "D6_REGIME_SEGMENTATION_PHASE",
    "build_phase_d6_regime_segmentation_report",
    "load_candles",
]
