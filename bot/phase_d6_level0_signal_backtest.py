from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_d6_baseline_backtest import load_d6_candles
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_cost_assumptions import build_phase_d6_cost_assumption_report
from bot.phase_d6_cost_aware_split_baseline import build_phase_d6_cost_aware_split_baseline_report
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


D6_LEVEL0_SIGNAL_BACKTEST_PHASE = "D6_level0_signal_backtest_scaffold_v1"
D6_LEVEL0_SIGNALS = {"fixed_sma_cross_5_20"}
SIGNAL_NAME = "fixed_sma_cross_5_20"
SIGNAL_VERSION = "v1"
FAST_WINDOW = 5
SLOW_WINDOW = 20
POSITION_FRACTION = "1.0"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "fixed_parameters_only": True,
        "strategy_parameter_mutation_allowed": False,
        "runtime_config_mutation_allowed": False,
    }


def _validate_inputs(*, signal_name: str, split_mode: str, initial_quote: Any) -> tuple[str, str, Any]:
    signal = str(signal_name or "").strip().lower()
    if signal not in D6_LEVEL0_SIGNALS:
        raise ValueError(f"unsupported_d6_level0_signal:{signal_name}")
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")
    initial = to_decimal(initial_quote)
    if initial <= ZERO:
        raise ValueError("initial_quote_must_be_positive")
    return signal, mode, initial


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


def _slice_candles(candles: List[Dict[str, Any]], range_record: Dict[str, Any]) -> List[Dict[str, Any]]:
    start = int(range_record.get("start_index") or 0)
    end = int(range_record.get("end_index_exclusive") or 0)
    return candles[start:end]


def _sma(closes: List[Any], idx: int, window: int) -> Optional[Any]:
    if idx + 1 < window:
        return None
    values = [to_decimal(value) for value in closes[idx + 1 - window: idx + 1]]
    return sum(values, ZERO) / to_decimal(window)


def _signal_metrics_for_range(
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
        "fixed_signal_scaffold_only",
        "candle_only_backtest",
        "cost_scenario_assumption_only",
        "no_fill_realism",
        "not_strategy_recommendation",
        "not_parameter_search",
        "not_optimization",
        "not_live_recommendation",
    ]
    warnings.extend(cost_report.get("warnings") or [])

    if len(candles) < 2:
        warnings.append("insufficient_candles_for_range_metrics")
        equity_curve = [initial]
        final_quote = initial
        total_cost_quote = ZERO
        exposed_bars = 0
        trades_count = 0
        round_trips = 0
        wins = 0
        losses = 0
        blocked = True
    else:
        closes = [to_decimal(candle["close"]) for candle in candles]
        quote = initial
        base = ZERO
        in_position = False
        trades_count = 0
        round_trips = 0
        wins = 0
        losses = 0
        total_cost_quote = ZERO
        exposed_bars = 0
        equity_curve: List[Any] = []
        previous_fast: Optional[Any] = None
        previous_slow: Optional[Any] = None
        entry_quote_basis = ZERO

        for idx, candle in enumerate(candles):
            close = to_decimal(candle["close"])
            fast = _sma(closes, idx, FAST_WINDOW)
            slow = _sma(closes, idx, SLOW_WINDOW)
            if fast is not None and slow is not None and previous_fast is not None and previous_slow is not None:
                crosses_above = previous_fast <= previous_slow and fast > slow
                crosses_below = previous_fast >= previous_slow and fast < slow
                if not in_position and crosses_above and quote > ZERO:
                    entry_quote_basis = quote
                    cost_quote = quote * entry_cost
                    total_cost_quote += cost_quote
                    base = (quote - cost_quote) / close
                    quote = ZERO
                    in_position = True
                    trades_count += 1
                elif in_position and crosses_below and base > ZERO:
                    gross = base * close
                    cost_quote = gross * exit_cost
                    total_cost_quote += cost_quote
                    quote = gross - cost_quote
                    base = ZERO
                    in_position = False
                    trades_count += 1
                    round_trips += 1
                    if quote > entry_quote_basis:
                        wins += 1
                    else:
                        losses += 1
                    entry_quote_basis = ZERO

            if fast is not None and slow is not None:
                previous_fast = fast
                previous_slow = slow
            if in_position:
                exposed_bars += 1
            equity_curve.append(quote + (base * close * (to_decimal("1") - exit_cost) if in_position else ZERO))

        if in_position and base > ZERO:
            close = to_decimal(candles[-1]["close"])
            gross = base * close
            cost_quote = gross * exit_cost
            total_cost_quote += cost_quote
            quote = gross - cost_quote
            base = ZERO
            in_position = False
            trades_count += 1
            round_trips += 1
            if quote > entry_quote_basis:
                wins += 1
            else:
                losses += 1
            equity_curve[-1] = quote
            warnings.append("forced_exit_at_range_end")

        final_quote = quote
        blocked = False

    return_metrics = build_return_metrics(initial_quote=initial, final_quote=final_quote)
    drawdown_metrics = build_drawdown_metrics(equity_curve)
    exposure_metrics = build_exposure_metrics(exposed_bars=exposed_bars, total_bars=len(candles))
    trade_metrics = build_trade_metrics(
        trades_count=trades_count,
        round_trips=round_trips,
        wins=wins,
        losses=losses,
    )
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
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
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
    return decimal_str(sum((to_decimal(value) for value in values), ZERO) / to_decimal(len(values)))


def _summary(per_split: List[Dict[str, Any]], blockers: List[str]) -> Dict[str, Any]:
    validation_returns: List[Any] = []
    test_returns: List[Any] = []
    test_drawdowns: List[Any] = []
    trades_counts: List[Any] = []
    warning_counts: Dict[str, int] = {}
    blocked_range_count = 0
    for split in per_split:
        for range_name in ("train", "validation", "test"):
            metrics = split.get(range_name) or {}
            if metrics.get("status") != "range_metrics_ready":
                blocked_range_count += 1
            for warning in metrics.get("warnings") or []:
                warning_counts[str(warning)] = warning_counts.get(str(warning), 0) + 1
            trades_counts.append(metrics.get("trade_metrics", {}).get("trades_count", 0))
        validation = split.get("validation") or {}
        test = split.get("test") or {}
        if validation.get("status") == "range_metrics_ready":
            validation_returns.append(validation["return_metrics"]["net_return_pct"])
        if test.get("status") == "range_metrics_ready":
            test_returns.append(test["return_metrics"]["net_return_pct"])
            test_drawdowns.append(test["drawdown_metrics"]["max_drawdown_pct"])
    return {
        "split_count": len(per_split),
        "blocked_range_count": blocked_range_count,
        "average_validation_net_return_pct": _average(validation_returns),
        "average_test_net_return_pct": _average(test_returns),
        "worst_test_max_drawdown_pct": decimal_str(max((to_decimal(v) for v in test_drawdowns), default=ZERO)),
        "total_trades_count": int(sum(int(to_decimal(v)) for v in trades_counts)),
        "warning_counts": warning_counts,
        "blocker_count": len(blockers),
        "usable_for_future_research": bool(per_split) and not blockers and blocked_range_count == 0,
    }


def build_phase_d6_level0_signal_backtest_report(
    *,
    candles_path: str | Path,
    signal_name: str = SIGNAL_NAME,
    cost_scenario: str = "standard_fee_only",
    split_mode: str = "holdout",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    initial_quote: Any = "1000",
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    signal, mode, initial = _validate_inputs(signal_name=signal_name, split_mode=split_mode, initial_quote=initial_quote)
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
    baseline_reference = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=candles_path,
        cost_scenario=cost_report["scenario_name"],
        split_mode=mode,
        baseline="buy_hold",
        train_count=int(train_count),
        validation_count=int(validation_count),
        test_count=int(test_count),
        step_count=int(step_count),
        max_splits=int(max_splits),
        initial_quote=initial,
        require_quality_ready=bool(require_quality_ready),
    )
    dataset_quality = dict(split_report.get("dataset_quality") or {})
    data_quality_ready = bool(dataset_quality.get("ready_for_walk_forward_scaffold"))
    split_usable = bool(split_report.get("usable_for_future_research"))
    blockers = list(split_report.get("blockers") or [])
    warnings = [
        "fixed_signal_scaffold_only",
        "candle_only_backtest",
        "cost_scenario_assumption_only",
        "not_strategy_recommendation",
        "not_parameter_search",
        "not_parameter_ranking",
        "not_optimization",
        "not_live_recommendation",
        "no_real_trading_signal_emission",
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
                "train": _signal_metrics_for_range(
                    candles=_slice_candles(loaded["candles"], split["train"]),
                    range_name="train",
                    range_record=split["train"],
                    initial_quote=initial,
                    cost_report=cost_report,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "validation": _signal_metrics_for_range(
                    candles=_slice_candles(loaded["candles"], split["validation"]),
                    range_name="validation",
                    range_record=split["validation"],
                    initial_quote=initial,
                    cost_report=cost_report,
                    data_quality_ready=data_quality_ready,
                    split_usable=split_usable,
                ),
                "test": _signal_metrics_for_range(
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
    status = "d6_level0_signal_backtest_report_ready" if summary["usable_for_future_research"] else "d6_level0_signal_backtest_report_blocked"
    return {
        "generated_at": now_iso(),
        "phase": D6_LEVEL0_SIGNAL_BACKTEST_PHASE,
        "status": status,
        "candles_path": str(assert_research_path(candles_path)),
        "product_id": loaded["product_id"],
        "timeframe": loaded["timeframe"],
        "candle_count": loaded["candle_count"],
        "first_candle_start": loaded["first_candle_start"],
        "last_candle_start": loaded["last_candle_start"],
        "gap_count": loaded["gap_count"],
        "signal_name": signal,
        "signal_version": SIGNAL_VERSION,
        "fixed_parameters": {
            "fast_window": FAST_WINDOW,
            "slow_window": SLOW_WINDOW,
            "position_fraction": POSITION_FRACTION,
            "entry_rule": "fast_sma_crosses_above_slow_sma_on_close",
            "exit_rule": "fast_sma_crosses_below_slow_sma_on_close",
            "forced_exit_at_range_end": True,
        },
        "cost_scenario": cost_report["scenario_name"],
        "cost_assumptions": cost_report,
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
        "baseline_reference": {
            "phase": baseline_reference.get("phase"),
            "baseline_type": baseline_reference.get("baseline_type"),
            "cost_scenario": baseline_reference.get("cost_scenario"),
            "summary": baseline_reference.get("summary"),
        },
        "warnings": sorted(set(warnings)),
        "blockers": blockers,
        "limitations": [
            "fixed_sma_cross_5_20_only_v1",
            "fixed_parameters_only",
            "candle_close_state_machine",
            "no_intrabar_fill_model",
            "no_post_only_queue_model",
            "no_orderbook_depth_model",
            "no_parameter_search",
            "not_a_live_trading_recommendation",
        ],
        **_safety_flags(),
    }


def write_level0_signal_backtest_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_LEVEL0_SIGNAL_BACKTEST_PHASE",
    "D6_LEVEL0_SIGNALS",
    "SIGNAL_NAME",
    "SIGNAL_VERSION",
    "FAST_WINDOW",
    "SLOW_WINDOW",
    "POSITION_FRACTION",
    "build_phase_d6_level0_signal_backtest_report",
    "write_level0_signal_backtest_report",
]
