from __future__ import annotations

from typing import Any, Dict, Iterable

from bot.phase_d6_backlearning_multisource_v6 import (
    build_backlearning_multisource_scaffold_v6,
    build_open_source_backlearning_pattern_map_v4,
    safety_flags,
)
from bot.phase_d6_metrics import now_iso


PHASE = "D6_backlearning_multisource_scaffold_v7"


def build_open_source_backlearning_pattern_map_v5() -> Dict[str, Any]:
    report = build_open_source_backlearning_pattern_map_v4()
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "open_source_backlearning_pattern_map_v5"
    report["status"] = "open_source_backlearning_pattern_map_v5_ready"
    report["v5_additions"] = [
        "cross_source_reference_visibility",
        "normal_vs_exploratory_gate_clarity",
        "source_mix_trial_accounting",
    ]
    return report


def build_backlearning_multisource_scaffold_v7(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str],
) -> Dict[str, Any]:
    report = build_backlearning_multisource_scaffold_v6(
        quality_summary=quality_summary,
        controller_result=controller_result,
        binance_reference=binance_reference,
        source_paths=source_paths,
    )
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "backlearning_multisource_scaffold_v7"
    report["status"] = "backlearning_multisource_scaffold_v7_ready"
    report["cross_source_reference_visibility"] = {
        "binance_reference_count": binance_reference.get("available_reference_count", 0),
        "reference_only": True,
        "shown_in_trial_metadata": True,
        "may_create_parameter_evidence": False,
    }
    report["normal_vs_exploratory_gate"] = {
        "normal_backtests_require_primary_coinbase_quality": True,
        "exploratory_only_can_use_warning_datasets": True,
        "exploratory_only_creates_parameter_evidence": False,
        "secondary_source_can_release_normal_backtest": False,
    }
    report["trial_accounting"]["source_mix_visibility_required"] = True
    report["human_review_checklist"].append("verify_exploratory_outputs_are_not_parameter_evidence")
    report["blockers"] = sorted(set([*report.get("blockers", []), "normal_backtests_deferred_until_primary_coinbase_quality_passes"]))
    return {**report, **safety_flags()}


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v7",
    "build_open_source_backlearning_pattern_map_v5",
    "safety_flags",
]
