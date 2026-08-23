from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from bot.phase_d6_baseline_backtest import load_d6_candles
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_cost_assumptions import build_phase_d6_cost_assumption_report
from bot.phase_d6_metrics import (
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


D6_COST_AWARE_SPLIT_BASELINE_PHASE = "D6_cost_aware_split_baseline_report_v1"
D6_COST_AWARE_SPLIT_BASELINES = {"buy_hold"}


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
    }


def _validate_initial_quote(value: Any) -> Any:
    initial = to_decimal(value)
    if initial <= ZERO:
        raise ValueError("initial_quote_must_be_positive")
    return initial


def _slice_candles(candles: List[Dict[str, Any]], range_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    start = int(range_record.get("start_index") or 0)
    end = int(range_record.get("end_index_exclusive") or 0)
    return candles[start:end]


def _cost_values(cost_report: Dict[str, Any]) -> Dict[str, Any]:
    derived = dict(cost_report.get("derived_costs") or {})
    entry_cost = to_decimal(derived.get("entry_cost_pct"))
    exit_cost = to_decimal(derived.get("exit_cost_pct"))
    if entry_cost < ZERO:
        raise ValueError("entry_cost_pct_must_not_be_negative")
    if exit_cost < ZERO:
        raise ValueError("exit_cost_pct_must_not_be_negative")
    if entry_cost >= to_decimal("1"):
        raise ValueError("entry_cost_pct_must_be_less_than_1")
    if exit_cost >= to_decimal("1"):
        raise ValueError("exit_cost_pct_must_be_less_than_1")
    return {
        "entry_cost_pct": entry_cost,
        "exit_cost_pct": exit_cost,
        "round_trip_cost_pct": to_decimal(derived.get("round_trip_cost_pct")),
    }


def _buy_hold_range_metrics(
    *,
    candles: List[Dict[str, Any]],
    range_name: str,
    range_record: Dict[str, Any],
    initial_quote: Any,
    cost_report: Dict[str, Any],
    data_quality_ready: bool,
    split_usable: bool,
) -> Dict[str, Any]:
    initial = to_decimal(initial_quote)
    costs = _cost_values(cost_report)
    entry_cost = costs["entry_cost_pct"]
    exit_cost = costs["exit_cost_pct"]
    warnings = [
        "research_cost_aware_split_baseline_only",
        "buy_hold_fixed_baseline_only",
        "cost_scenario_assumption_only",
        "not_strategy_recommendation",
        "not_parameter_ranking",
        "not_parameter_search",
        "not_optimization",
    ]
    warnings.extend(cost_report.get("warnings") or [])

    if len(candles) < 2:
        warnings.append("insufficient_candles_for_range_metrics")
        final_quote = initial
        total_cost_quote = ZERO
        equity_curve = [initial]
        exposed_bars = 0
        trades_count = 0
        round_trips = 0
        blocked = True
    else:
        entry = to_decimal(candles[0]["close"])
        exit_price = to_decimal(candles[-1]["close"])
        quote_after_entry_cost = initial * (to_decimal("1") - entry_cost)
        base = quote_after_entry_cost / entry
        equity_curve = [base * to_decimal(candle["close"]) * (to_decimal("1") - exit_cost) for candle in candles]
        final_quote = base * exit_price * (to_decimal("1") - exit_cost)
        total_cost_quote = (initial * entry_cost) + (base * exit_price * exit_cost)
        exposed_bars = len(candles)
        trades_count = 1
        round_trips = 1
        blocked = False

    return_metrics = build_return_metrics(initial_quote=initial, final_quote=final_quote)
    drawdown_metrics = build_drawdown_metrics(equity_curve)
    exposure_metrics = build_exposure_metrics(exposed_bars=exposed_bars, total_bars=len(candles))
    trade_metrics = build_trade_metrics(trades_count=trades_count, round_trips=round_trips)
    cost_metrics = build_fee_metrics(fees_quote=total_cost_quote, initial_quote=initial)
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
        "cost_scenario": cost_report.get("scenario_name"),
        "candle_count": len(candles),
        "first_candle_start": candles[0]["start"] if candles else None,
        "last_candle_start": candles[-1]["start"] if candles else None,
        "return_metrics": return_metrics,
        "drawdown_metrics": drawdown_metrics,
        "exposure_metrics": exposure_metrics,
        "trade_metrics": trade_metrics,
        "cost_metrics": {
            **cost_metrics,
            "total_cost_quote_estimate": cost_metrics["fees_paid_quote_estimate"],
            "entry_cost_pct": decimal_str(entry_cost),
            "exit_cost_pct": decimal_str(exit_cost),
            "round_trip_cost_pct": decimal_str(costs["round_trip_cost_pct"]),
        },
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


def build_phase_d6_cost_aware_split_baseline_report(
    *,
    candles_path: str | Path,
    cost_scenario: str = "standard_fee_only",
    split_mode: str = "holdout",
    baseline: str = "buy_hold",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    initial_quote: Any = "1000",
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    baseline_n = str(baseline or "").strip().lower()
    if baseline_n not in D6_COST_AWARE_SPLIT_BASELINES:
        raise ValueError(f"unsupported_d6_cost_aware_split_baseline:{baseline}")
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")
    initial = _validate_initial_quote(initial_quote)
    cost_report = build_phase_d6_cost_assumption_report(scenario_name=cost_scenario)

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
        "research_cost_aware_split_baseline_report_only",
        "single_cost_scenario_only",
        "not_cost_scenario_ranking",
        "not_strategy_recommendation",
        "not_parameter_ranking",
        "not_parameter_search",
        "not_optimization",
        "no_live_recommendation",
    ]
    warnings.extend(cost_report.get("warnings") or [])
    if loaded.get("gap_count"):
        warnings.append("candle_gaps_detected")
    if not split_usable:
        warnings.append("walk_forward_split_unusable")

    per_split: List[Dict[str, Any]] = []
    for split in split_report.get("splits") or []:
        per_split.append(
            {
                "split_index": split["split_index"],
                "split_mode": split["split_mode"],
                "train": _buy_hold_range_metrics(
                    candles=_slice_candles(loaded["candles"], split["train"]),
                    range_name="train",
                    range_record=split["train"],
                    initial_quote=initial,
                    cost_report=cost_report,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "validation": _buy_hold_range_metrics(
                    candles=_slice_candles(loaded["candles"], split["validation"]),
                    range_name="validation",
                    range_record=split["validation"],
                    initial_quote=initial,
                    cost_report=cost_report,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "test": _buy_hold_range_metrics(
                    candles=_slice_candles(loaded["candles"], split["test"]),
                    range_name="test",
                    range_record=split["test"],
                    initial_quote=initial,
                    cost_report=cost_report,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
            }
        )

    summary = _summary(per_split, blockers)
    status = (
        "d6_cost_aware_split_baseline_report_ready"
        if summary["usable_for_future_research"]
        else "d6_cost_aware_split_baseline_report_blocked"
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_COST_AWARE_SPLIT_BASELINE_PHASE,
        "status": status,
        "candles_path": str(assert_research_path(candles_path)),
        "product_id": loaded["product_id"],
        "timeframe": loaded["timeframe"],
        "candle_count": loaded["candle_count"],
        "first_candle_start": loaded["first_candle_start"],
        "last_candle_start": loaded["last_candle_start"],
        "gap_count": loaded["gap_count"],
        "baseline_type": baseline_n,
        "baseline_label": "buy_hold_cost_aware_split_research_scaffold",
        "cost_scenario": cost_report["scenario_name"],
        "cost_assumptions": cost_report,
        "derived_costs": cost_report["derived_costs"],
        "split_mode": mode,
        "train_count": int(train_count),
        "validation_count": int(validation_count),
        "test_count": int(test_count),
        "step_count": int(step_count),
        "max_splits": int(max_splits),
        "split_count": len(per_split),
        "initial_quote": decimal_str(initial),
        "dataset_quality": dataset_quality,
        "split_coverage": split_report.get("split_coverage"),
        "per_split": per_split,
        "summary": summary,
        "warnings": sorted(set(warnings)),
        "blockers": blockers,
        "limitations": [
            "buy_hold_only_v1",
            "single_cost_scenario_only",
            "uses_fixed_chronological_splits",
            "cost_scenarios_are_research_assumptions_only",
            "no_post_only_fill_model",
            "no_orderbook_depth_model",
            "not_a_live_trading_recommendation",
        ],
        **_safety_flags(),
    }


def write_cost_aware_split_baseline_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_COST_AWARE_SPLIT_BASELINE_PHASE",
    "D6_COST_AWARE_SPLIT_BASELINES",
    "build_phase_d6_cost_aware_split_baseline_report",
    "write_cost_aware_split_baseline_report",
]
