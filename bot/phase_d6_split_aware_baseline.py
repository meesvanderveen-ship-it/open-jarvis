from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from bot.phase_d6_baseline_backtest import load_d6_candles
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import (
    ONE,
    ZERO,
    build_drawdown_metrics,
    build_exposure_metrics,
    build_fee_metrics,
    build_metric_warnings,
    build_return_metrics,
    build_trade_metrics,
    d6_metric_safety_flags,
    decimal_str,
    now_iso,
    to_decimal,
)
from bot.phase_d6_walk_forward_splits import (
    D6_WALK_FORWARD_SPLIT_MODES,
    build_phase_d6_walk_forward_split_report,
)


D6_SPLIT_AWARE_BASELINE_PHASE = "D6_split_aware_baseline_report_v1"
D6_SPLIT_AWARE_BASELINES = {"buy_hold"}


def _validate_money_inputs(*, initial_quote: Any, fee_pct: Any) -> tuple[Any, Any]:
    initial = to_decimal(initial_quote)
    fee = to_decimal(fee_pct)
    if initial <= ZERO:
        raise ValueError("initial_quote_must_be_positive")
    if fee < ZERO or fee >= ONE:
        raise ValueError("fee_pct_must_be_between_0_and_1")
    return initial, fee


def _slice_candles(candles: List[Dict[str, Any]], range_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    start = int(range_record.get("start_index") or 0)
    end = int(range_record.get("end_index_exclusive") or 0)
    return candles[start:end]


def _buy_hold_range_metrics(
    *,
    candles: List[Dict[str, Any]],
    range_name: str,
    range_record: Dict[str, Any],
    initial_quote: Any,
    fee_pct: Any,
    data_quality_ready: bool,
    split_usable: bool,
) -> Dict[str, Any]:
    initial = to_decimal(initial_quote)
    fee = to_decimal(fee_pct)
    warnings = [
        "research_split_aware_baseline_only",
        "buy_hold_fixed_baseline_only",
        "no_post_only_fill_model_yet",
        "no_slippage_model_yet",
        "not_parameter_search",
        "not_optimization",
    ]
    if len(candles) < 2:
        warnings.append("insufficient_candles_for_range_metrics")
        final_quote = initial
        fees_quote = ZERO
        equity_curve = [initial]
        exposed_bars = 0
        trades_count = 0
        round_trips = 0
        blocked = True
    else:
        entry = to_decimal(candles[0]["close"])
        exit_price = to_decimal(candles[-1]["close"])
        quote_after_entry_fee = initial * (ONE - fee)
        base = quote_after_entry_fee / entry
        equity_curve = [base * to_decimal(c["close"]) for c in candles]
        final_quote = base * exit_price * (ONE - fee)
        fees_quote = initial * fee + (base * exit_price * fee)
        exposed_bars = len(candles)
        trades_count = 1
        round_trips = 1
        blocked = False

    return_metrics = build_return_metrics(initial_quote=initial, final_quote=final_quote)
    drawdown_metrics = build_drawdown_metrics(equity_curve)
    exposure_metrics = build_exposure_metrics(exposed_bars=exposed_bars, total_bars=len(candles))
    trade_metrics = build_trade_metrics(trades_count=trades_count, round_trips=round_trips)
    fee_metrics = build_fee_metrics(fees_quote=fees_quote, initial_quote=initial)
    warnings.extend(
        build_metric_warnings(
            trades_count=trade_metrics["trades_count"],
            max_drawdown_value=drawdown_metrics["max_drawdown"],
            exposure_value=exposure_metrics["exposure"],
            data_quality_ready=data_quality_ready,
            split_usable=split_usable and not blocked,
        )
    )

    return {
        "range_name": range_name,
        "range": dict(range_record),
        "status": "range_metrics_ready" if not blocked else "range_metrics_blocked",
        "baseline_type": "buy_hold",
        "candle_count": len(candles),
        "first_candle_start": candles[0]["start"] if candles else None,
        "last_candle_start": candles[-1]["start"] if candles else None,
        "return_metrics": return_metrics,
        "drawdown_metrics": drawdown_metrics,
        "exposure_metrics": exposure_metrics,
        "trade_metrics": trade_metrics,
        "fee_metrics": fee_metrics,
        "warnings": sorted(set(warnings)),
    }


def _average(values: List[Any]) -> str:
    if not values:
        return "0"
    total = sum((to_decimal(value) for value in values), ZERO)
    return decimal_str(total / to_decimal(len(values)))


def _summary(per_split: List[Dict[str, Any]], blockers: List[str]) -> Dict[str, Any]:
    validation_returns: List[Any] = []
    test_returns: List[Any] = []
    test_drawdowns: List[Any] = []
    warning_counts: Dict[str, int] = {}
    blocked_range_count = 0

    for split in per_split:
        for range_name in ("train", "validation", "test"):
            metrics = split.get(range_name) or {}
            if metrics.get("status") != "range_metrics_ready":
                blocked_range_count += 1
            for warning in metrics.get("warnings") or []:
                warning_counts[str(warning)] = warning_counts.get(str(warning), 0) + 1
        validation = split.get("validation") or {}
        test = split.get("test") or {}
        if validation.get("status") == "range_metrics_ready":
            validation_returns.append(validation["return_metrics"]["net_return_pct"])
        if test.get("status") == "range_metrics_ready":
            test_returns.append(test["return_metrics"]["net_return_pct"])
            test_drawdowns.append(test["drawdown_metrics"]["max_drawdown_pct"])

    worst_test_drawdown = max((to_decimal(value) for value in test_drawdowns), default=ZERO)
    return {
        "split_count": len(per_split),
        "blocked_range_count": blocked_range_count,
        "average_validation_net_return_pct": _average(validation_returns),
        "average_test_net_return_pct": _average(test_returns),
        "worst_test_max_drawdown_pct": decimal_str(worst_test_drawdown),
        "warning_counts": warning_counts,
        "blocker_count": len(blockers),
        "usable_for_future_research": bool(per_split) and not blockers and blocked_range_count == 0,
    }


def build_phase_d6_split_aware_baseline_report(
    *,
    candles_path: str | Path,
    split_mode: str = "holdout",
    baseline: str = "buy_hold",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    initial_quote: Any = "1000",
    fee_pct: Any = "0.0040",
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    baseline_n = str(baseline or "").strip().lower()
    if baseline_n not in D6_SPLIT_AWARE_BASELINES:
        raise ValueError(f"unsupported_d6_split_aware_baseline:{baseline}")
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")
    initial, fee = _validate_money_inputs(initial_quote=initial_quote, fee_pct=fee_pct)

    loaded = load_d6_candles(candles_path)
    split_report = build_phase_d6_walk_forward_split_report(
        candles_path=candles_path,
        split_mode=mode,
        train_count=int(train_count),
        validation_count=int(validation_count),
        test_count=int(test_count),
        step_count=int(step_count),
        max_splits=int(max_splits),
        require_quality_ready=bool(require_quality_ready),
    )
    dataset_quality = dict(split_report.get("dataset_quality") or {})
    data_quality_ready = bool(dataset_quality.get("ready_for_walk_forward_scaffold"))
    split_usable = bool(split_report.get("usable_for_future_research"))
    blockers = list(split_report.get("blockers") or [])
    warnings = [
        "research_split_aware_baseline_report_only",
        "buy_hold_fixed_baseline_only",
        "not_strategy_recommendation",
        "not_parameter_ranking",
        "not_parameter_search",
        "not_optimization",
        "no_live_recommendation",
    ]
    if loaded.get("gap_count"):
        warnings.append("candle_gaps_detected")
    if not split_usable:
        warnings.append("walk_forward_split_unusable")

    per_split: List[Dict[str, Any]] = []
    for split in split_report.get("splits") or []:
        train_candles = _slice_candles(loaded["candles"], split["train"])
        validation_candles = _slice_candles(loaded["candles"], split["validation"])
        test_candles = _slice_candles(loaded["candles"], split["test"])
        per_split.append(
            {
                "split_index": split["split_index"],
                "split_mode": split["split_mode"],
                "train": _buy_hold_range_metrics(
                    candles=train_candles,
                    range_name="train",
                    range_record=split["train"],
                    initial_quote=initial,
                    fee_pct=fee,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "validation": _buy_hold_range_metrics(
                    candles=validation_candles,
                    range_name="validation",
                    range_record=split["validation"],
                    initial_quote=initial,
                    fee_pct=fee,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "test": _buy_hold_range_metrics(
                    candles=test_candles,
                    range_name="test",
                    range_record=split["test"],
                    initial_quote=initial,
                    fee_pct=fee,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
            }
        )

    summary = _summary(per_split, blockers)
    status = "d6_split_aware_baseline_report_ready" if summary["usable_for_future_research"] else "d6_split_aware_baseline_report_blocked"
    return {
        "generated_at": now_iso(),
        "phase": D6_SPLIT_AWARE_BASELINE_PHASE,
        "status": status,
        "candles_path": str(assert_research_path(candles_path)),
        "product_id": loaded["product_id"],
        "timeframe": loaded["timeframe"],
        "candle_count": loaded["candle_count"],
        "first_candle_start": loaded["first_candle_start"],
        "last_candle_start": loaded["last_candle_start"],
        "gap_count": loaded["gap_count"],
        "baseline_type": baseline_n,
        "baseline_label": "buy_hold_split_aware_research_scaffold",
        "split_mode": mode,
        "train_count": int(train_count),
        "validation_count": int(validation_count),
        "test_count": int(test_count),
        "step_count": int(step_count),
        "max_splits": int(max_splits),
        "split_count": len(per_split),
        "initial_quote": decimal_str(initial),
        "fee_pct": decimal_str(fee),
        "dataset_quality": dataset_quality,
        "split_coverage": split_report.get("split_coverage"),
        "per_split": per_split,
        "summary": summary,
        "warnings": sorted(set(warnings)),
        "blockers": blockers,
        "limitations": [
            "buy_hold_only_v1",
            "uses_fixed_chronological_splits",
            "no_post_only_fill_model",
            "no_slippage_model",
            "not_a_live_trading_recommendation",
        ],
        **d6_metric_safety_flags(),
    }


def write_split_aware_baseline_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_SPLIT_AWARE_BASELINE_PHASE",
    "D6_SPLIT_AWARE_BASELINES",
    "build_phase_d6_split_aware_baseline_report",
    "write_split_aware_baseline_report",
]
