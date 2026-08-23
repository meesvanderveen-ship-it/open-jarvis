from __future__ import annotations

from typing import Any, Dict, Iterable

from bot.phase_d6_backlearning_multisource_v7 import (
    build_backlearning_multisource_scaffold_v7,
    build_open_source_backlearning_pattern_map_v5,
    safety_flags,
)
from bot.phase_d6_metrics import now_iso


PHASE = "D6_backlearning_multisource_scaffold_v8"


def build_open_source_backlearning_pattern_map_v6() -> Dict[str, Any]:
    report = build_open_source_backlearning_pattern_map_v5()
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "open_source_backlearning_pattern_map_v6"
    report["status"] = "open_source_backlearning_pattern_map_v6_ready"
    report["v6_additions"] = [
        "fail_closed_fetch_accounting",
        "reference_unavailable_without_retry_spam",
        "operator_review_before_next_batch",
    ]
    return report


def build_backlearning_multisource_scaffold_v8(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str],
) -> Dict[str, Any]:
    report = build_backlearning_multisource_scaffold_v7(
        quality_summary=quality_summary,
        controller_result=controller_result,
        binance_reference=binance_reference,
        source_paths=source_paths,
    )
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "backlearning_multisource_scaffold_v8"
    report["status"] = "backlearning_multisource_scaffold_v8_ready"
    report["fetch_failure_accounting"] = {
        "fail_closed_reason_required": True,
        "operator_review_required_before_next_batch": True,
        "reference_unavailable_does_not_mutate_primary_data": True,
    }
    report["normal_vs_exploratory_gate"]["normal_backtests_require_primary_coinbase_quality"] = True
    report["normal_vs_exploratory_gate"]["exploratory_only_creates_parameter_evidence"] = False
    report["hard_gate"]["learning_to_execution_enabled"] = False
    return {**report, **safety_flags()}


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v8",
    "build_open_source_backlearning_pattern_map_v6",
    "safety_flags",
]
