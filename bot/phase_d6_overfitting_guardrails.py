from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_research_review_pack import build_phase_d6_research_review_pack


D6_OVERFITTING_GUARDRAILS_PHASE = "D6_overfitting_trial_accounting_guardrails_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "live_recommendation": False,
        "strategy_parameter_mutation_allowed": False,
        "runtime_config_mutation_allowed": False,
        "human_review_required": True,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
    }


def load_review_pack(path: str | Path) -> Dict[str, Any]:
    safe_path = assert_research_path(path)
    return json.loads(safe_path.read_text(encoding="utf-8"))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _source_summary(pack: Dict[str, Any]) -> Dict[str, Any]:
    inputs = dict(pack.get("input_summary") or {})
    quality = dict(pack.get("dataset_quality_summary") or {})
    baseline = dict(pack.get("baseline_evidence_summary") or {})
    signal = dict(pack.get("signal_evidence_summary") or {})
    trial = dict(pack.get("trial_accounting_preview") or {})
    return {
        "source_phase": pack.get("phase"),
        "source_status": pack.get("status"),
        "candle_file_count": _as_int(inputs.get("candle_file_count") or trial.get("candle_file_count")),
        "scenario_count": _as_int(inputs.get("scenario_count") or trial.get("cost_scenario_count")),
        "signal_count": _as_int(trial.get("signal_count") or len(signal.get("signal_names") or [])),
        "signal_names": list(trial.get("signal_names") or signal.get("signal_names") or []),
        "split_mode": inputs.get("split_mode") or trial.get("split_mode"),
        "split_config_count": 1,
        "dataset_quality_class": quality.get("aggregate_quality_class"),
        "baseline_report_count": _as_int(baseline.get("report_count") or trial.get("baseline_report_count")),
        "signal_report_count": _as_int(signal.get("report_count") or trial.get("signal_report_count")),
        "source_contains_rankings": bool(pack.get("contains_rankings", False)),
        "source_contains_recommendations": bool(pack.get("contains_recommendations", False)),
        "source_contains_live_instructions": bool(pack.get("contains_live_instructions", False)),
    }


def _trial_accounting(source: Dict[str, Any]) -> Dict[str, Any]:
    baseline_count = _as_int(source.get("baseline_report_count"))
    signal_count = _as_int(source.get("signal_report_count"))
    total = baseline_count + signal_count
    return {
        "file_count": _as_int(source.get("candle_file_count")),
        "scenario_count": _as_int(source.get("scenario_count")),
        "signal_count": _as_int(source.get("signal_count")),
        "split_config_count": _as_int(source.get("split_config_count")),
        "baseline_report_count": baseline_count,
        "signal_report_count": signal_count,
        "total_evidence_report_count": total,
        "trial_count": total,
        "trial_count_is_descriptive_only": True,
        "optimization_performed": False,
        "parameter_search_performed": False,
        "ranking_performed": False,
    }


def _degrees_of_freedom(trial: Dict[str, Any]) -> Dict[str, Any]:
    file_count = max(_as_int(trial.get("file_count")), 1)
    scenario_count = max(_as_int(trial.get("scenario_count")), 1)
    signal_count = max(_as_int(trial.get("signal_count")), 1)
    split_config_count = max(_as_int(trial.get("split_config_count")), 1)
    estimated = file_count * scenario_count * signal_count * split_config_count
    return {
        "file_axis_count": file_count,
        "cost_scenario_axis_count": scenario_count,
        "signal_axis_count": signal_count,
        "split_config_axis_count": split_config_count,
        "estimated_degrees_of_research_freedom": estimated,
        "estimate_is_descriptive_only": True,
    }


def _guardrail_warnings(source: Dict[str, Any], trial: Dict[str, Any], dof: Dict[str, Any]) -> List[str]:
    warnings = [
        "descriptive_guardrails_only",
        "not_formal_pbo",
        "not_deflated_sharpe_ratio",
        "not_parameter_review",
        "not_optimization",
        "not_parameter_search",
    ]
    if trial["file_count"] < 3:
        warnings.append("limited_file_or_ticker_breadth")
    if trial["scenario_count"] > 1:
        warnings.append("multiple_cost_scenarios_inspected_not_ranked")
    if trial["signal_count"] <= 1:
        warnings.append("single_fixed_signal_only")
    if trial["split_config_count"] <= 1:
        warnings.append("single_split_configuration_only")
    if trial["total_evidence_report_count"] == 0:
        warnings.append("no_evidence_reports_present")
    elif trial["total_evidence_report_count"] >= 20:
        warnings.append("trial_count_high_requires_separate_research_approval")
    elif trial["total_evidence_report_count"] >= 8:
        warnings.append("trial_count_growing_track_cherry_picking_risk")
    if dof["estimated_degrees_of_research_freedom"] >= 12:
        warnings.append("research_degrees_of_freedom_growing")
    if source.get("source_contains_rankings"):
        warnings.append("source_claims_rankings_review_required")
    if source.get("source_contains_recommendations"):
        warnings.append("source_claims_recommendations_review_required")
    if source.get("source_contains_live_instructions"):
        warnings.append("source_claims_live_instructions_blocked")
    return sorted(set(warnings))


def _guardrail_class(warnings: List[str], blockers: List[str], trial: Dict[str, Any]) -> str:
    if blockers:
        return "insufficient_for_parameter_review"
    if "no_evidence_reports_present" in warnings:
        return "insufficient_for_parameter_review"
    if trial["file_count"] < 3 or trial["signal_count"] <= 1 or trial["split_config_count"] <= 1:
        return "exploratory_only"
    if trial["total_evidence_report_count"] >= 20:
        return "exploratory_only"
    return "usable_for_limited_research"


def build_phase_d6_overfitting_guardrails_report(
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
    source_pack = review_pack
    source_mode = "provided_review_pack_object"
    if review_pack_path is not None:
        source_pack = load_review_pack(review_pack_path)
        source_mode = "review_pack_json_path"
    elif source_pack is None:
        if candle_paths is None:
            raise ValueError("d6_overfitting_guardrails_requires_review_pack_or_candle_paths")
        source_pack = build_phase_d6_research_review_pack(
            candle_paths=candle_paths,
            cost_scenarios=cost_scenarios,
            split_mode=split_mode,
            train_count=train_count,
            validation_count=validation_count,
            test_count=test_count,
            step_count=step_count,
            max_splits=max_splits,
            initial_quote=initial_quote,
            require_quality_ready=require_quality_ready,
        )
        source_mode = "built_from_explicit_local_candles"

    source = _source_summary(source_pack or {})
    trial = _trial_accounting(source)
    dof = _degrees_of_freedom(trial)
    blockers: List[str] = []
    if source.get("source_contains_rankings"):
        blockers.append("source_contains_rankings_blocked")
    if source.get("source_contains_recommendations"):
        blockers.append("source_contains_recommendations_blocked")
    if source.get("source_contains_live_instructions"):
        blockers.append("source_contains_live_instructions_blocked")
    warnings = _guardrail_warnings(source, trial, dof)
    guardrail_class = _guardrail_class(warnings, blockers, trial)

    return {
        "generated_at": now_iso(),
        "phase": D6_OVERFITTING_GUARDRAILS_PHASE,
        "status": "d6_overfitting_guardrails_ready",
        "source_mode": source_mode,
        "source_summary": source,
        "trial_accounting": trial,
        "research_degrees_of_freedom": dof,
        "guardrail_class": guardrail_class,
        "parameter_review_allowed": False,
        "optimization_allowed": False,
        "broader_signal_expansion_requires_human_approval": True,
        "guardrail_warnings": warnings,
        "blockers": sorted(set(blockers)),
        "limitations": [
            "descriptive_trial_accounting_only",
            "not_formal_probability_of_backtest_overfitting",
            "not_deflated_sharpe_ratio",
            "no_statistical_significance_claim",
            "no_parameter_review_approval",
            "no_live_trading_guidance",
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
            "increase_dataset_breadth_before_parameter_review",
            "add_regime_segmentation_before_parameter_review",
            "add_formal_oos_degradation_checks",
            "keep_do_not_change_parameters_as_valid_outcome",
        ],
        **_safety_flags(),
    }


def guardrails_to_markdown(report: Dict[str, Any]) -> str:
    source = dict(report.get("source_summary") or {})
    trial = dict(report.get("trial_accounting") or {})
    dof = dict(report.get("research_degrees_of_freedom") or {})
    lines = [
        "# D.6 Overfitting / Trial-Accounting Guardrails",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- guardrail_class: `{report.get('guardrail_class', '')}`",
        f"- parameter_review_allowed: `{report.get('parameter_review_allowed')}`",
        f"- optimization_allowed: `{report.get('optimization_allowed')}`",
        f"- file_count: `{trial.get('file_count', 0)}`",
        f"- scenario_count: `{trial.get('scenario_count', 0)}`",
        f"- signal_count: `{trial.get('signal_count', 0)}`",
        f"- split_config_count: `{trial.get('split_config_count', 0)}`",
        f"- total_evidence_report_count: `{trial.get('total_evidence_report_count', 0)}`",
        f"- estimated_degrees_of_research_freedom: `{dof.get('estimated_degrees_of_research_freedom', 0)}`",
        f"- dataset_quality_class: `{source.get('dataset_quality_class', '')}`",
        "",
        "## Guardrail Warnings",
        "",
    ]
    lines.extend(f"- `{warning}`" for warning in report.get("guardrail_warnings") or [])
    lines.extend(
        [
            "",
            "## Safety",
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
            f"- contains_rankings: `{report.get('contains_rankings')}`",
            f"- contains_recommendations: `{report.get('contains_recommendations')}`",
            f"- contains_live_instructions: `{report.get('contains_live_instructions')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_guardrails(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_guardrails(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(guardrails_to_markdown(report), encoding="utf-8")
    return path


__all__ = [
    "D6_OVERFITTING_GUARDRAILS_PHASE",
    "build_phase_d6_overfitting_guardrails_report",
    "guardrails_to_markdown",
    "load_review_pack",
    "write_json_guardrails",
    "write_markdown_guardrails",
]
