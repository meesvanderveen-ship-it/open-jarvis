from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_cost_assumptions import list_cost_scenarios
from bot.phase_d6_level0_signal_backtest import (
    FAST_WINDOW,
    POSITION_FRACTION,
    SIGNAL_NAME,
    SIGNAL_VERSION,
    SLOW_WINDOW,
    build_phase_d6_level0_signal_backtest_report,
)
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_walk_forward_splits import D6_WALK_FORWARD_SPLIT_MODES


D6_LEVEL0_SIGNAL_BUNDLE_PHASE = "D6_level0_signal_bundle_v1"
DEFAULT_LEVEL0_SIGNAL_BUNDLE_SCENARIOS = ["standard_fee_only"]


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "fixed_parameters_only": True,
        "strategy_parameter_mutation_allowed": False,
        "runtime_config_mutation_allowed": False,
        "contains_rankings": False,
        "contains_recommendations": False,
    }


def normalize_candle_paths(paths: Iterable[str | Path]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = assert_research_path(raw)
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    if not out:
        raise ValueError("d6_level0_signal_bundle_requires_at_least_one_candle_file")
    return out


def normalize_cost_scenarios(values: Optional[Iterable[Any]] = None) -> List[str]:
    allowed = set(list_cost_scenarios())
    raw_values = list(DEFAULT_LEVEL0_SIGNAL_BUNDLE_SCENARIOS if values is None else values)
    out: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        scenario = str(raw or "").strip().lower()
        if scenario not in allowed:
            raise ValueError(f"unsupported_d6_cost_scenario:{raw}")
        if scenario in seen:
            continue
        seen.add(scenario)
        out.append(scenario)
    if not out:
        raise ValueError("d6_level0_signal_bundle_requires_at_least_one_cost_scenario")
    return out


def _compact_report(report: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(report.get("summary") or {})
    warnings = list(report.get("warnings") or [])
    blockers = list(report.get("blockers") or [])
    return {
        "product_id": report.get("product_id"),
        "timeframe": report.get("timeframe"),
        "candles_path": report.get("candles_path"),
        "candle_count": report.get("candle_count"),
        "gap_count": report.get("gap_count"),
        "signal_name": report.get("signal_name"),
        "signal_version": report.get("signal_version"),
        "cost_scenario": report.get("cost_scenario"),
        "split_mode": report.get("split_mode"),
        "split_count": report.get("split_count"),
        "average_validation_net_return_pct": summary.get("average_validation_net_return_pct"),
        "average_test_net_return_pct": summary.get("average_test_net_return_pct"),
        "worst_test_max_drawdown_pct": summary.get("worst_test_max_drawdown_pct"),
        "total_trades_count": summary.get("total_trades_count"),
        "usable_for_future_research": summary.get("usable_for_future_research"),
        "warning_count": len(warnings),
        "blocker_count": len(blockers),
        "warnings": warnings,
        "blockers": blockers,
    }


def _summary(rows: List[Dict[str, Any]], candle_paths: List[str], scenarios: List[str]) -> Dict[str, Any]:
    warning_counts: Dict[str, int] = {}
    usable_report_count = 0
    blocked_report_count = 0
    for row in rows:
        if row.get("usable_for_future_research"):
            usable_report_count += 1
        else:
            blocked_report_count += 1
        for warning in row.get("warnings") or []:
            warning_counts[str(warning)] = warning_counts.get(str(warning), 0) + 1
    return {
        "candle_file_count": len(candle_paths),
        "scenario_count": len(scenarios),
        "report_count": len(rows),
        "products": sorted({str(row.get("product_id")) for row in rows if row.get("product_id")}),
        "timeframes": sorted({str(row.get("timeframe")) for row in rows if row.get("timeframe")}),
        "scenario_names": list(scenarios),
        "signal_names": sorted({str(row.get("signal_name")) for row in rows if row.get("signal_name")}),
        "usable_report_count": usable_report_count,
        "blocked_report_count": blocked_report_count,
        "warning_counts": warning_counts,
        "contains_rankings": False,
        "contains_recommendations": False,
    }


def build_phase_d6_level0_signal_bundle(
    *,
    candle_paths: Iterable[str | Path],
    cost_scenarios: Optional[Iterable[Any]] = None,
    signal_name: str = SIGNAL_NAME,
    split_mode: str = "holdout",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    initial_quote: Any = "1000",
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    signal = str(signal_name or "").strip().lower()
    if signal != SIGNAL_NAME:
        raise ValueError(f"unsupported_d6_level0_signal:{signal_name}")
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")

    paths = normalize_candle_paths(candle_paths)
    scenarios = normalize_cost_scenarios(cost_scenarios)
    rows: List[Dict[str, Any]] = []
    warnings = [
        "research_level0_signal_bundle_only",
        "compact_summary_only",
        "fixed_signal_scaffold_only",
        "not_signal_ranking",
        "not_ticker_ranking",
        "not_cost_scenario_ranking",
        "not_parameter_ranking",
        "not_parameter_search",
        "not_optimization",
        "no_live_recommendation",
        "no_real_trading_signal_emission",
    ]

    for path in paths:
        for scenario in scenarios:
            report = build_phase_d6_level0_signal_backtest_report(
                candles_path=path,
                signal_name=signal,
                cost_scenario=scenario,
                split_mode=mode,
                train_count=train_count,
                validation_count=validation_count,
                test_count=test_count,
                step_count=step_count,
                max_splits=max_splits,
                initial_quote=initial_quote,
                require_quality_ready=require_quality_ready,
            )
            rows.append(_compact_report(report))

    return {
        "generated_at": now_iso(),
        "phase": D6_LEVEL0_SIGNAL_BUNDLE_PHASE,
        "status": "d6_level0_signal_bundle_ready",
        "candle_paths": paths,
        "cost_scenarios": scenarios,
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
        "split_mode": mode,
        "train_count": int(train_count),
        "validation_count": int(validation_count),
        "test_count": int(test_count),
        "step_count": int(step_count),
        "max_splits": int(max_splits),
        "initial_quote": str(initial_quote),
        "summary": _summary(rows, paths, scenarios),
        "reports": rows,
        "warnings": warnings,
        "limitations": [
            "compact_bundle_only",
            "fixed_sma_cross_5_20_only_v1",
            "one_split_configuration_per_bundle_v1",
            "no_signal_ranking",
            "no_ticker_ranking",
            "no_cost_scenario_ranking",
            "no_parameter_ranking",
            "no_parameter_search",
            "not_a_live_trading_recommendation",
        ],
        **_safety_flags(),
    }


def bundle_to_markdown(bundle: Dict[str, Any]) -> str:
    summary = dict(bundle.get("summary") or {})
    lines = [
        "# D.6 Level-0 Signal Bundle",
        "",
        f"- generated_at: `{bundle.get('generated_at', '')}`",
        f"- signal_name: `{bundle.get('signal_name', '')}`",
        f"- report_count: `{summary.get('report_count', 0)}`",
        f"- candle_file_count: `{summary.get('candle_file_count', 0)}`",
        f"- scenario_count: `{summary.get('scenario_count', 0)}`",
        f"- contains_rankings: `{summary.get('contains_rankings')}`",
        f"- contains_recommendations: `{summary.get('contains_recommendations')}`",
        "",
        "| product | timeframe | scenario | signal | split_count | validation_return_pct | test_return_pct | total_trades | usable | blockers |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in bundle.get("reports") or []:
        lines.append(
            "| {product_id} | {timeframe} | {cost_scenario} | {signal_name} | {split_count} | {average_validation_net_return_pct} | {average_test_net_return_pct} | {total_trades_count} | {usable_for_future_research} | {blocker_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "Safety:",
            "",
            f"- research_only: `{bundle.get('research_only')}`",
            f"- no_coinbase_call: `{bundle.get('no_coinbase_call')}`",
            f"- no_live_action: `{bundle.get('no_live_action')}`",
            f"- state_write_performed: `{bundle.get('state_write_performed')}`",
            f"- no_optimization: `{bundle.get('no_optimization')}`",
            f"- parameter_search_performed: `{bundle.get('parameter_search_performed')}`",
            f"- signal_generation_performed: `{bundle.get('signal_generation_performed')}`",
            f"- live_recommendation: `{bundle.get('live_recommendation')}`",
            f"- fixed_parameters_only: `{bundle.get('fixed_parameters_only')}`",
            f"- parameter_change_allowed: `{bundle.get('parameter_change_allowed')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_bundle(bundle: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_bundle(bundle: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle_to_markdown(bundle), encoding="utf-8")
    return path


__all__ = [
    "D6_LEVEL0_SIGNAL_BUNDLE_PHASE",
    "DEFAULT_LEVEL0_SIGNAL_BUNDLE_SCENARIOS",
    "build_phase_d6_level0_signal_bundle",
    "bundle_to_markdown",
    "write_json_bundle",
    "write_markdown_bundle",
    "normalize_candle_paths",
    "normalize_cost_scenarios",
]
