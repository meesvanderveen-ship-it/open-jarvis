from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_cost_assumptions import build_phase_d6_cost_assumption_catalog, list_cost_scenarios
from bot.phase_d6_cost_aware_baseline_bundle import build_phase_d6_cost_aware_baseline_bundle
from bot.phase_d6_dataset_quality_aggregate import build_phase_d6_dataset_quality_aggregate_report
from bot.phase_d6_level0_signal_backtest import FAST_WINDOW, POSITION_FRACTION, SIGNAL_NAME, SIGNAL_VERSION, SLOW_WINDOW
from bot.phase_d6_level0_signal_bundle import build_phase_d6_level0_signal_bundle
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_walk_forward_splits import D6_WALK_FORWARD_SPLIT_MODES


D6_RESEARCH_REVIEW_PACK_PHASE = "D6_research_review_pack_v1"
DEFAULT_REVIEW_PACK_SCENARIOS = ["standard_fee_only"]


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "fixed_parameters_only": True,
        "strategy_parameter_mutation_allowed": False,
        "runtime_config_mutation_allowed": False,
        "human_review_required": True,
        "parameter_review_approved": False,
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
        raise ValueError("d6_research_review_pack_requires_at_least_one_candle_file")
    return out


def normalize_cost_scenarios(values: Optional[Iterable[Any]] = None) -> List[str]:
    allowed = set(list_cost_scenarios())
    raw_values = list(DEFAULT_REVIEW_PACK_SCENARIOS if values is None else values)
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
        raise ValueError("d6_research_review_pack_requires_at_least_one_cost_scenario")
    return out


def _compact_cost_assumptions(catalog: Dict[str, Any]) -> Dict[str, Any]:
    scenarios = []
    for report in catalog.get("scenarios") or []:
        scenarios.append(
            {
                "scenario_name": report.get("scenario_name"),
                "description": report.get("description"),
                "round_trip_cost_pct": (report.get("derived_costs") or {}).get("round_trip_cost_pct"),
                "entry_cost_pct": (report.get("derived_costs") or {}).get("entry_cost_pct"),
                "exit_cost_pct": (report.get("derived_costs") or {}).get("exit_cost_pct"),
                "warning_count": len(report.get("warnings") or []),
            }
        )
    return {
        "scenario_count": catalog.get("scenario_count"),
        "scenario_names": catalog.get("scenario_names"),
        "scenarios": scenarios,
    }


def _warning_counts(*bundles: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for bundle in bundles:
        for warning in bundle.get("warnings") or []:
            counts[str(warning)] = counts.get(str(warning), 0) + 1
        summary = dict(bundle.get("summary") or {})
        for warning, count in (summary.get("warning_counts") or {}).items():
            counts[str(warning)] = counts.get(str(warning), 0) + int(count)
    return counts


def _trial_accounting_preview(
    *,
    candle_paths: List[str],
    cost_scenarios: List[str],
    baseline_bundle: Dict[str, Any],
    signal_bundle: Dict[str, Any],
    split_mode: str,
) -> Dict[str, Any]:
    baseline_summary = dict(baseline_bundle.get("summary") or {})
    signal_summary = dict(signal_bundle.get("summary") or {})
    signal_names = list(signal_summary.get("signal_names") or [])
    baseline_report_count = int(baseline_summary.get("report_count") or 0)
    signal_report_count = int(signal_summary.get("report_count") or 0)
    warnings = [
        "trial_accounting_preview_only",
        "not_overfitting_statistic",
        "not_parameter_review",
    ]
    if len(candle_paths) < 3:
        warnings.append("limited_candle_file_breadth")
    if len(cost_scenarios) > 1:
        warnings.append("multiple_cost_scenarios_present_not_ranked")
    if len(signal_names) <= 1:
        warnings.append("single_fixed_signal_only")
    if baseline_report_count + signal_report_count > 1:
        warnings.append("multiple_research_reports_present_not_ranked")
    return {
        "split_mode": split_mode,
        "candle_file_count": len(candle_paths),
        "cost_scenario_count": len(cost_scenarios),
        "signal_count": len(signal_names),
        "signal_names": signal_names,
        "baseline_report_count": baseline_report_count,
        "signal_report_count": signal_report_count,
        "total_evidence_report_count": baseline_report_count + signal_report_count,
        "optimization_performed": False,
        "parameter_search_performed": False,
        "ranking_performed": False,
        "trial_count_is_descriptive_only": True,
        "warnings": warnings,
    }


def build_phase_d6_research_review_pack(
    *,
    candle_paths: Iterable[str | Path],
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
    paths = normalize_candle_paths(candle_paths)
    scenarios = normalize_cost_scenarios(cost_scenarios)
    mode = str(split_mode or "").strip().lower()
    if mode not in D6_WALK_FORWARD_SPLIT_MODES:
        raise ValueError(f"unsupported_walk_forward_split_mode:{split_mode}")

    quality = build_phase_d6_dataset_quality_aggregate_report(candle_paths=paths)
    baseline_bundle = build_phase_d6_cost_aware_baseline_bundle(
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
    signal_bundle = build_phase_d6_level0_signal_bundle(
        candle_paths=paths,
        cost_scenarios=scenarios,
        signal_name=SIGNAL_NAME,
        split_mode=mode,
        train_count=train_count,
        validation_count=validation_count,
        test_count=test_count,
        step_count=step_count,
        max_splits=max_splits,
        initial_quote=initial_quote,
        require_quality_ready=require_quality_ready,
    )
    cost_catalog = build_phase_d6_cost_assumption_catalog(scenarios=scenarios)

    quality_summary = dict(quality.get("summary") or {})
    baseline_summary = dict(baseline_bundle.get("summary") or {})
    signal_summary = dict(signal_bundle.get("summary") or {})
    blockers = list(quality_summary.get("blockers") or [])
    if baseline_summary.get("blocked_report_count"):
        blockers.append("baseline_evidence_has_blocked_reports")
    if signal_summary.get("blocked_report_count"):
        blockers.append("signal_evidence_has_blocked_reports")
    trial_preview = _trial_accounting_preview(
        candle_paths=paths,
        cost_scenarios=scenarios,
        baseline_bundle=baseline_bundle,
        signal_bundle=signal_bundle,
        split_mode=mode,
    )

    warnings = [
        "research_review_pack_only",
        "human_review_required",
        "not_parameter_review",
        "not_strategy_recommendation",
        "not_parameter_search",
        "not_optimization",
        "not_ticker_ranking",
        "not_cost_scenario_ranking",
        "not_signal_ranking",
        "no_live_recommendation",
    ]
    warnings.extend(trial_preview["warnings"])
    if blockers:
        warnings.append("review_pack_has_blockers")

    return {
        "generated_at": now_iso(),
        "phase": D6_RESEARCH_REVIEW_PACK_PHASE,
        "status": "d6_research_review_pack_ready",
        "input_summary": {
            "candle_paths": paths,
            "candle_file_count": len(paths),
            "cost_scenarios": scenarios,
            "scenario_count": len(scenarios),
            "signal_name": SIGNAL_NAME,
            "signal_version": SIGNAL_VERSION,
            "fixed_parameters": {
                "fast_window": FAST_WINDOW,
                "slow_window": SLOW_WINDOW,
                "position_fraction": POSITION_FRACTION,
            },
            "split_mode": mode,
            "train_count": int(train_count),
            "validation_count": int(validation_count),
            "test_count": int(test_count),
            "step_count": int(step_count),
            "max_splits": int(max_splits),
            "initial_quote": str(initial_quote),
        },
        "dataset_quality_summary": quality_summary,
        "dataset_quality_reports": list(quality.get("reports") or []),
        "baseline_evidence_summary": baseline_summary,
        "baseline_evidence_rows": list(baseline_bundle.get("reports") or []),
        "signal_evidence_summary": signal_summary,
        "signal_evidence_rows": list(signal_bundle.get("reports") or []),
        "cost_assumption_summary": _compact_cost_assumptions(cost_catalog),
        "trial_accounting_preview": trial_preview,
        "warning_counts": _warning_counts(quality, baseline_bundle, signal_bundle),
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
        "limitations": [
            "compact_human_review_artifact_v1",
            "fixed_sma_cross_5_20_only_v1",
            "buy_hold_baseline_only_v1",
            "one_split_configuration_per_pack_v1",
            "trial_accounting_preview_only",
            "no_formal_pbo_or_deflated_sharpe_v1",
            "no_signal_ranking",
            "no_ticker_ranking",
            "no_cost_scenario_ranking",
            "no_parameter_ranking",
            "not_a_live_trading_recommendation",
        ],
        "prohibited_interpretations": [
            "do_not_infer_best_ticker",
            "do_not_infer_best_cost_scenario",
            "do_not_infer_best_signal",
            "do_not_infer_parameter_change",
            "do_not_infer_live_readiness",
            "do_not_use_as_execution_signal",
            "do_not_use_as_parameter_review_approval",
        ],
        "suggested_next_research_steps": [
            "add_formal_overfitting_trial_accounting_guardrails",
            "expand_dataset_coverage_only_with_separate_approval",
            "add_regime_segmentation_before_parameter_review",
            "keep_do_not_change_parameters_as_valid_outcome",
        ],
        **_safety_flags(),
    }


def review_pack_to_markdown(pack: Dict[str, Any]) -> str:
    inputs = dict(pack.get("input_summary") or {})
    quality = dict(pack.get("dataset_quality_summary") or {})
    baseline = dict(pack.get("baseline_evidence_summary") or {})
    signal = dict(pack.get("signal_evidence_summary") or {})
    trial = dict(pack.get("trial_accounting_preview") or {})
    lines = [
        "# D.6 Research Review Pack",
        "",
        f"- generated_at: `{pack.get('generated_at', '')}`",
        f"- candle_file_count: `{inputs.get('candle_file_count', 0)}`",
        f"- scenario_count: `{inputs.get('scenario_count', 0)}`",
        f"- signal_name: `{inputs.get('signal_name', '')}`",
        f"- split_mode: `{inputs.get('split_mode', '')}`",
        f"- human_review_required: `{pack.get('human_review_required')}`",
        f"- parameter_review_approved: `{pack.get('parameter_review_approved')}`",
        f"- contains_rankings: `{pack.get('contains_rankings')}`",
        f"- contains_recommendations: `{pack.get('contains_recommendations')}`",
        "",
        "## Evidence Summary",
        "",
        f"- dataset_quality: `{quality.get('aggregate_quality_class', '')}`",
        f"- usable_dataset_count: `{quality.get('quality_counts', {}).get('good', 0) + quality.get('quality_counts', {}).get('usable_with_warnings', 0)}`",
        f"- baseline_report_count: `{baseline.get('report_count', 0)}`",
        f"- usable_baseline_report_count: `{baseline.get('usable_report_count', 0)}`",
        f"- signal_report_count: `{signal.get('report_count', 0)}`",
        f"- usable_signal_report_count: `{signal.get('usable_report_count', 0)}`",
        f"- total_evidence_report_count: `{trial.get('total_evidence_report_count', 0)}`",
        "",
        "## Prohibited Interpretations",
        "",
    ]
    lines.extend(f"- `{item}`" for item in pack.get("prohibited_interpretations") or [])
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- research_only: `{pack.get('research_only')}`",
            f"- no_coinbase_call: `{pack.get('no_coinbase_call')}`",
            f"- no_live_action: `{pack.get('no_live_action')}`",
            f"- state_write_performed: `{pack.get('state_write_performed')}`",
            f"- no_optimization: `{pack.get('no_optimization')}`",
            f"- parameter_search_performed: `{pack.get('parameter_search_performed')}`",
            f"- signal_generation_performed: `{pack.get('signal_generation_performed')}`",
            f"- live_recommendation: `{pack.get('live_recommendation')}`",
            f"- learning_to_execution_allowed: `{pack.get('learning_to_execution_allowed')}`",
            f"- parameter_change_allowed: `{pack.get('parameter_change_allowed')}`",
            f"- contains_live_instructions: `{pack.get('contains_live_instructions')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_review_pack(pack: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_review_pack(pack: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review_pack_to_markdown(pack), encoding="utf-8")
    return path


__all__ = [
    "D6_RESEARCH_REVIEW_PACK_PHASE",
    "DEFAULT_REVIEW_PACK_SCENARIOS",
    "build_phase_d6_research_review_pack",
    "review_pack_to_markdown",
    "write_json_review_pack",
    "write_markdown_review_pack",
    "normalize_candle_paths",
    "normalize_cost_scenarios",
]
