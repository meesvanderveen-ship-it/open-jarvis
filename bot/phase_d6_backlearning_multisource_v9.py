from __future__ import annotations

from typing import Any, Dict, Iterable

from bot.phase_d6_backlearning_multisource_v8 import (
    build_backlearning_multisource_scaffold_v8,
    build_open_source_backlearning_pattern_map_v6,
    safety_flags,
)
from bot.phase_d6_metrics import now_iso


PHASE = "D6_backlearning_multisource_scaffold_v9"


def build_open_source_backlearning_pattern_map_v7() -> Dict[str, Any]:
    report = build_open_source_backlearning_pattern_map_v6()
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "open_source_backlearning_pattern_map_v7"
    report["status"] = "open_source_backlearning_pattern_map_v7_ready"
    report["v7_additions"] = [
        "chunk_batch_review_accounting",
        "primary_source_quality_gate_reaffirmed",
        "no_learning_to_execution_bridge",
    ]
    return report


def build_backlearning_multisource_scaffold_v9(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str],
) -> Dict[str, Any]:
    report = build_backlearning_multisource_scaffold_v8(
        quality_summary=quality_summary,
        controller_result=controller_result,
        binance_reference=binance_reference,
        source_paths=source_paths,
    )
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "backlearning_multisource_scaffold_v9"
    report["status"] = "backlearning_multisource_scaffold_v9_ready"
    report["v9_batch_governance"] = {
        "max_coinbase_1h_chunks_per_sprint": 3,
        "merge_only_after_exact_candidate_validation": True,
        "secondary_source_reference_only": True,
        "normal_backtest_release_allowed": False,
    }
    report["hard_gate"]["learning_to_execution_enabled"] = False
    report["hard_gate"]["parameter_evidence_created"] = False
    return {**report, **safety_flags()}


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v9",
    "build_open_source_backlearning_pattern_map_v7",
    "safety_flags",
]
