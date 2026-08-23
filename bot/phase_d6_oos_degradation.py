from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_cost_assumptions import list_cost_scenarios
from bot.phase_d6_cost_aware_split_baseline import build_phase_d6_cost_aware_split_baseline_report
from bot.phase_d6_level0_signal_backtest import SIGNAL_NAME, build_phase_d6_level0_signal_backtest_report
from bot.phase_d6_metrics import ZERO, d6_metric_safety_flags, decimal_str, now_iso, to_decimal
from bot.phase_d6_research_review_pack import build_phase_d6_research_review_pack
from bot.phase_d6_walk_forward_splits import D6_WALK_FORWARD_SPLIT_MODES


D6_OOS_DEGRADATION_PHASE = "D6_out_of_sample_degradation_checks_v1"
DEFAULT_OOS_DEGRADATION_SCENARIOS = ["standard_fee_only"]


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "strategy_parameter_mutation_allowed": False,
        "runtime_config_mutation_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "broader_signal_expansion_requires_human_approval": True,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
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
        raise ValueError("d6_oos_degradation_requires_at_least_one_candle_file")
    return out


def normalize_cost_scenarios(values: Optional[Iterable[Any]] = None) -> List[str]:
    allowed = set(list_cost_scenarios())
    raw_values = list(DEFAULT_OOS_DEGRADATION_SCENARIOS if values is None else values)
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
        raise ValueError("d6_oos_degradation_requires_at_least_one_cost_scenario")
    return out


def load_review_pack(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    return json.loads(safe_path.read_text(encoding="utf-8"))


def _average_return(per_split: List[Dict[str, Any]], range_name: str) -> Any | None:
    values: List[Any] = []
    for split in per_split:
        metrics = dict(split.get(range_name) or {})
        if metrics.get("status") == "range_metrics_ready":
            values.append(metrics.get("return_metrics", {}).get("net_return_pct"))
    if not values:
        return None
    return sum((to_decimal(value) for value in values), ZERO) / to_decimal(len(values))


def _blocked_range_count(per_split: List[Dict[str, Any]]) -> int:
    blocked = 0
    for split in per_split:
        for range_name in ("train", "validation", "test"):
            if dict(split.get(range_name) or {}).get("status") != "range_metrics_ready":
                blocked += 1
    return blocked


def _degradation_class(
    *,
    train_return: Any | None,
    validation_return: Any | None,
    test_return: Any | None,
    blocked_range_count: int,
) -> str:
    if blocked_range_count:
        return "blocked_or_unusable"
    if train_return is None or validation_return is None or test_return is None:
        return "no_oos_check_available"
    train_to_test = to_decimal(train_return) - to_decimal(test_return)
    validation_to_test = to_decimal(validation_return) - to_decimal(test_return)
    if train_to_test >= to_decimal("25") or validation_to_test >= to_decimal("15"):
        return "severe_degradation"
    if train_to_test >= to_decimal("10") or validation_to_test >= to_decimal("5"):
        return "moderate_degradation"
    if train_to_test > ZERO or validation_to_test > ZERO:
        return "mild_degradation"
    return "stable_or_improving"


def _row_from_full_report(report: Dict[str, Any], *, evidence_type: str) -> Dict[str, Any]:
    per_split = list(report.get("per_split") or [])
    train_return = _average_return(per_split, "train")
    validation_return = _average_return(per_split, "validation")
    test_return = _average_return(per_split, "test")
    blocked = _blocked_range_count(per_split)
    row_class = _degradation_class(
        train_return=train_return,
        validation_return=validation_return,
        test_return=test_return,
        blocked_range_count=blocked,
    )
    train_to_validation = None if train_return is None or validation_return is None else to_decimal(train_return) - to_decimal(validation_return)
    validation_to_test = None if validation_return is None or test_return is None else to_decimal(validation_return) - to_decimal(test_return)
    train_to_test = None if train_return is None or test_return is None else to_decimal(train_return) - to_decimal(test_return)
    warnings = [
        "oos_degradation_diagnostic_only",
        "not_strategy_recommendation",
        "not_parameter_review",
        "not_parameter_search",
        "not_optimization",
    ]
    if row_class == "severe_degradation":
        warnings.append("severe_oos_degradation")
    if row_class == "moderate_degradation":
        warnings.append("moderate_oos_degradation")
    if row_class == "blocked_or_unusable":
        warnings.append("blocked_or_unusable_evidence")
    if len(per_split) <= 1:
        warnings.append("single_split_only")
    return {
        "evidence_type": evidence_type,
        "product_id": report.get("product_id"),
        "timeframe": report.get("timeframe"),
        "candles_path": report.get("candles_path"),
        "cost_scenario": report.get("cost_scenario"),
        "baseline_type": report.get("baseline_type"),
        "signal_name": report.get("signal_name"),
        "split_mode": report.get("split_mode"),
        "split_count": len(per_split),
        "average_train_net_return_pct": None if train_return is None else decimal_str(train_return),
        "average_validation_net_return_pct": None if validation_return is None else decimal_str(validation_return),
        "average_test_net_return_pct": None if test_return is None else decimal_str(test_return),
        "train_to_validation_degradation_pct_points": None if train_to_validation is None else decimal_str(train_to_validation),
        "validation_to_test_degradation_pct_points": None if validation_to_test is None else decimal_str(validation_to_test),
        "train_to_test_degradation_pct_points": None if train_to_test is None else decimal_str(train_to_test),
        "degradation_class": row_class,
        "blocked_range_count": blocked,
        "usable_for_future_research": bool(report.get("summary", {}).get("usable_for_future_research")),
        "warning_count": len(warnings),
        "warnings": sorted(set(warnings)),
    }


def _row_from_compact_review(row: Dict[str, Any], *, evidence_type: str) -> Dict[str, Any]:
    validation_return = row.get("average_validation_net_return_pct")
    test_return = row.get("average_test_net_return_pct")
    validation_to_test = None if validation_return is None or test_return is None else to_decimal(validation_return) - to_decimal(test_return)
    row_class = "no_oos_check_available"
    warnings = [
        "compact_review_pack_row_only",
        "train_metrics_unavailable",
        "no_train_to_validation_or_train_to_test_check",
        "not_parameter_review",
        "not_strategy_recommendation",
    ]
    if validation_to_test is not None:
        if validation_to_test >= to_decimal("15"):
            row_class = "severe_degradation"
            warnings.append("severe_validation_to_test_degradation")
        elif validation_to_test >= to_decimal("5"):
            row_class = "moderate_degradation"
            warnings.append("moderate_validation_to_test_degradation")
        elif validation_to_test > ZERO:
            row_class = "mild_degradation"
        else:
            row_class = "stable_or_improving"
    return {
        "evidence_type": evidence_type,
        "product_id": row.get("product_id"),
        "timeframe": row.get("timeframe"),
        "candles_path": row.get("candles_path"),
        "cost_scenario": row.get("cost_scenario"),
        "baseline_type": row.get("baseline_type"),
        "signal_name": row.get("signal_name"),
        "split_mode": row.get("split_mode"),
        "split_count": row.get("split_count"),
        "average_train_net_return_pct": None,
        "average_validation_net_return_pct": validation_return,
        "average_test_net_return_pct": test_return,
        "train_to_validation_degradation_pct_points": None,
        "validation_to_test_degradation_pct_points": None if validation_to_test is None else decimal_str(validation_to_test),
        "train_to_test_degradation_pct_points": None,
        "degradation_class": row_class,
        "blocked_range_count": row.get("blocker_count", 0),
        "usable_for_future_research": bool(row.get("usable_for_future_research")),
        "warning_count": len(warnings),
        "warnings": sorted(set(warnings)),
    }


def _summary(rows: List[Dict[str, Any]], *, source_summary: Dict[str, Any]) -> Dict[str, Any]:
    class_counts: Dict[str, int] = {}
    warning_counts: Dict[str, int] = {}
    max_train_to_test = None
    severe_count = 0
    blocked_count = 0
    for row in rows:
        cls = str(row.get("degradation_class") or "no_oos_check_available")
        class_counts[cls] = class_counts.get(cls, 0) + 1
        if cls == "severe_degradation":
            severe_count += 1
        if cls == "blocked_or_unusable":
            blocked_count += 1
        for warning in row.get("warnings") or []:
            warning_counts[str(warning)] = warning_counts.get(str(warning), 0) + 1
        value = row.get("train_to_test_degradation_pct_points")
        if value is not None:
            dec = to_decimal(value)
            max_train_to_test = dec if max_train_to_test is None else max(max_train_to_test, dec)
    check_class = "no_oos_check_available"
    if blocked_count:
        check_class = "blocked_or_unusable"
    elif severe_count:
        check_class = "severe_degradation"
    elif class_counts.get("moderate_degradation"):
        check_class = "moderate_degradation"
    elif class_counts.get("mild_degradation"):
        check_class = "mild_degradation"
    elif class_counts.get("stable_or_improving"):
        check_class = "stable_or_improving"
    return {
        "row_count": len(rows),
        "degradation_class_counts": class_counts,
        "overall_degradation_class": check_class,
        "max_train_to_test_degradation_pct_points": None if max_train_to_test is None else decimal_str(max_train_to_test),
        "severe_degradation_count": severe_count,
        "blocked_or_unusable_count": blocked_count,
        "warning_counts": warning_counts,
        "single_file": int(source_summary.get("candle_file_count") or 0) <= 1,
        "single_signal": int(source_summary.get("signal_count") or 0) <= 1,
        "single_split_config": int(source_summary.get("split_config_count") or 1) <= 1,
        "parameter_review_allowed": False,
    }


def _source_summary_from_review_pack(pack: Dict[str, Any]) -> Dict[str, Any]:
    inputs = dict(pack.get("input_summary") or {})
    trial = dict(pack.get("trial_accounting_preview") or {})
    return {
        "source_phase": pack.get("phase"),
        "source_mode": "review_pack_compact_rows",
        "candle_file_count": int(inputs.get("candle_file_count") or trial.get("candle_file_count") or 0),
        "scenario_count": int(inputs.get("scenario_count") or trial.get("cost_scenario_count") or 0),
        "signal_count": int(trial.get("signal_count") or 0),
        "split_config_count": 1,
        "baseline_report_count": int(trial.get("baseline_report_count") or 0),
        "signal_report_count": int(trial.get("signal_report_count") or 0),
        "total_evidence_report_count": int(trial.get("total_evidence_report_count") or 0),
        "train_metrics_available": False,
    }


def _guardrail_warnings(summary: Dict[str, Any], source_summary: Dict[str, Any]) -> List[str]:
    warnings = [
        "oos_degradation_diagnostic_only",
        "not_parameter_review",
        "not_strategy_recommendation",
        "not_parameter_search",
        "not_optimization",
        "not_live_recommendation",
    ]
    if not source_summary.get("train_metrics_available"):
        warnings.append("train_metrics_unavailable_for_some_or_all_rows")
    if summary.get("single_file"):
        warnings.append("single_file_oos_context")
    if summary.get("single_signal"):
        warnings.append("single_signal_oos_context")
    if summary.get("single_split_config"):
        warnings.append("single_split_configuration_oos_context")
    if summary.get("severe_degradation_count"):
        warnings.append("severe_oos_degradation_present")
    if summary.get("blocked_or_unusable_count"):
        warnings.append("blocked_or_unusable_evidence_present")
    return sorted(set(warnings))


def build_phase_d6_oos_degradation_report(
    *,
    review_pack: Optional[Dict[str, Any]] = None,
    review_pack_path: str | Path | None = None,
    candle_paths: Optional[Iterable[str | Path]] = None,
    cost_scenarios: Optional[Iterable[Any]] = None,
    split_mode: str = "holdout",
    train_count: int = 210,
    validation_count: int = 70,
    test_count: int = 70,
    step_count: int = 70,
    max_splits: int = 12,
    initial_quote: Any = "1000",
    require_quality_ready: bool = True,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    source_mode = "review_pack_object"
    if review_pack_path is not None:
        review_pack = load_review_pack(review_pack_path)
        source_mode = "review_pack_json_path"

    if review_pack is not None:
        source_summary = _source_summary_from_review_pack(review_pack)
        source_summary["source_mode"] = source_mode
        for row in review_pack.get("baseline_evidence_rows") or []:
            rows.append(_row_from_compact_review(dict(row), evidence_type="baseline"))
        for row in review_pack.get("signal_evidence_rows") or []:
            rows.append(_row_from_compact_review(dict(row), evidence_type="signal"))
    else:
        if candle_paths is None:
            raise ValueError("d6_oos_degradation_requires_review_pack_or_candle_paths")
        paths = normalize_candle_paths(candle_paths)
        scenarios = normalize_cost_scenarios(cost_scenarios)
        mode = str(split_mode or "").strip().lower()
        if mode not in D6_WALK_FORWARD_SPLIT_MODES:
            raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")
        source_summary = {
            "source_phase": "built_from_explicit_local_candles",
            "source_mode": "built_from_explicit_local_candles",
            "candle_file_count": len(paths),
            "scenario_count": len(scenarios),
            "signal_count": 1,
            "split_config_count": 1,
            "baseline_report_count": len(paths) * len(scenarios),
            "signal_report_count": len(paths) * len(scenarios),
            "total_evidence_report_count": len(paths) * len(scenarios) * 2,
            "train_metrics_available": True,
        }
        # Build the review pack for parity with the evidence-pack workflow and to reuse its validation gates.
        build_phase_d6_research_review_pack(
            candle_paths=paths,
            cost_scenarios=scenarios,
            split_mode=mode,
            train_count=train_count,
            validation_count=validation_count,
            test_count=test_count,
            step_count=step_count,
            max_splits=max_splits,
            initial_quote=initial_quote,
            require_quality_ready=require_quality_ready,
        )
        for path in paths:
            for scenario in scenarios:
                rows.append(
                    _row_from_full_report(
                        build_phase_d6_cost_aware_split_baseline_report(
                            candles_path=path,
                            cost_scenario=scenario,
                            split_mode=mode,
                            baseline="buy_hold",
                            train_count=train_count,
                            validation_count=validation_count,
                            test_count=test_count,
                            step_count=step_count,
                            max_splits=max_splits,
                            initial_quote=initial_quote,
                            require_quality_ready=require_quality_ready,
                        ),
                        evidence_type="baseline",
                    )
                )
                rows.append(
                    _row_from_full_report(
                        build_phase_d6_level0_signal_backtest_report(
                            candles_path=path,
                            signal_name=SIGNAL_NAME,
                            cost_scenario=scenario,
                            split_mode=mode,
                            train_count=train_count,
                            validation_count=validation_count,
                            test_count=test_count,
                            step_count=step_count,
                            max_splits=max_splits,
                            initial_quote=initial_quote,
                            require_quality_ready=require_quality_ready,
                        ),
                        evidence_type="signal",
                    )
                )

    summary = _summary(rows, source_summary=source_summary)
    guardrail_warnings = _guardrail_warnings(summary, source_summary)
    blockers: List[str] = []
    if summary["blocked_or_unusable_count"]:
        blockers.append("blocked_or_unusable_evidence_present")
    return {
        "generated_at": now_iso(),
        "phase": D6_OOS_DEGRADATION_PHASE,
        "status": "d6_oos_degradation_report_ready",
        "source_summary": source_summary,
        "degradation_summary": summary,
        "baseline_degradation_rows": [row for row in rows if row.get("evidence_type") == "baseline"],
        "signal_degradation_rows": [row for row in rows if row.get("evidence_type") == "signal"],
        "guardrail_warnings": guardrail_warnings,
        "blockers": blockers,
        "limitations": [
            "descriptive_oos_degradation_only",
            "not_parameter_review",
            "not_strategy_recommendation",
            "no_statistical_significance_claim",
            "no_regime_segmentation_v1",
            "no_formal_pbo_or_deflated_sharpe",
        ],
        "prohibited_interpretations": [
            "do_not_infer_best_ticker",
            "do_not_infer_best_cost_scenario",
            "do_not_infer_best_signal",
            "do_not_infer_best_strategy",
            "do_not_infer_parameter_change",
            "do_not_infer_live_readiness",
            "do_not_use_as_execution_signal",
            "do_not_use_as_parameter_review_approval",
        ],
        "suggested_next_research_steps": [
            "add_regime_segmentation_scaffold",
            "increase_split_and_dataset_breadth_before_parameter_review",
            "keep_do_not_change_parameters_as_valid_outcome",
        ],
        **_safety_flags(),
    }


def load_review_pack(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    return json.loads(safe_path.read_text(encoding="utf-8"))


def degradation_to_markdown(report: Dict[str, Any]) -> str:
    source = dict(report.get("source_summary") or {})
    summary = dict(report.get("degradation_summary") or {})
    lines = [
        "# D.6 Out-of-Sample Degradation Checks",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- overall_degradation_class: `{summary.get('overall_degradation_class', '')}`",
        f"- row_count: `{summary.get('row_count', 0)}`",
        f"- candle_file_count: `{source.get('candle_file_count', 0)}`",
        f"- scenario_count: `{source.get('scenario_count', 0)}`",
        f"- signal_count: `{source.get('signal_count', 0)}`",
        f"- parameter_review_allowed: `{report.get('parameter_review_allowed')}`",
        f"- contains_rankings: `{report.get('contains_rankings')}`",
        "",
        "| type | product | timeframe | scenario | signal/baseline | train_pct | validation_pct | test_pct | class |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in list(report.get("baseline_degradation_rows") or []) + list(report.get("signal_degradation_rows") or []):
        label = row.get("signal_name") or row.get("baseline_type") or ""
        lines.append(
            "| {evidence_type} | {product_id} | {timeframe} | {cost_scenario} | {label} | {train} | {validation} | {test} | {cls} |".format(
                evidence_type=row.get("evidence_type"),
                product_id=row.get("product_id"),
                timeframe=row.get("timeframe"),
                cost_scenario=row.get("cost_scenario"),
                label=label,
                train=row.get("average_train_net_return_pct"),
                validation=row.get("average_validation_net_return_pct"),
                test=row.get("average_test_net_return_pct"),
                cls=row.get("degradation_class"),
            )
        )
    lines.extend(
        [
            "",
            "Safety:",
            "",
            f"- research_only: `{report.get('research_only')}`",
            f"- no_coinbase_call: `{report.get('no_coinbase_call')}`",
            f"- no_live_action: `{report.get('no_live_action')}`",
            f"- state_write_performed: `{report.get('state_write_performed')}`",
            f"- no_optimization: `{report.get('no_optimization')}`",
            f"- parameter_search_performed: `{report.get('parameter_search_performed')}`",
            f"- signal_generation_performed: `{report.get('signal_generation_performed')}`",
            f"- live_recommendation: `{report.get('live_recommendation')}`",
            f"- parameter_change_allowed: `{report.get('parameter_change_allowed')}`",
            f"- contains_live_instructions: `{report.get('contains_live_instructions')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_degradation(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_degradation(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(degradation_to_markdown(report), encoding="utf-8")
    return path


__all__ = [
    "D6_OOS_DEGRADATION_PHASE",
    "DEFAULT_OOS_DEGRADATION_SCENARIOS",
    "build_phase_d6_oos_degradation_report",
    "degradation_to_markdown",
    "load_review_pack",
    "normalize_candle_paths",
    "normalize_cost_scenarios",
    "write_json_degradation",
    "write_markdown_degradation",
]
