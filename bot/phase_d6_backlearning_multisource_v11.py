from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from bot.phase_d6_backlearning_multisource_v10 import (
    build_backlearning_multisource_scaffold_v10,
    build_open_source_backlearning_pattern_map_v8,
    safety_flags,
)
from bot.phase_d6_metrics import now_iso


PHASE = "D6_backlearning_multisource_scaffold_v11"


def build_open_source_backlearning_pattern_map_v9() -> Dict[str, Any]:
    report = build_open_source_backlearning_pattern_map_v8()
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "open_source_backlearning_pattern_map_v9"
    report["status"] = "open_source_backlearning_pattern_map_v9_ready"
    report["v9_additions"] = [
        "batch_checkpoint_hash_review",
        "reference_visibility_without_quality_release",
        "holdout_freeze_before_human_review",
        "fill_realism_adapter_placeholders_reaffirmed",
    ]
    return report


def build_backlearning_multisource_scaffold_v11(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str | Path],
) -> Dict[str, Any]:
    report = build_backlearning_multisource_scaffold_v10(
        quality_summary=quality_summary,
        controller_result=controller_result,
        binance_reference=binance_reference,
        source_paths=source_paths,
    )
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "backlearning_multisource_scaffold_v11"
    report["status"] = "backlearning_multisource_scaffold_v11_ready"
    report["chunk_batch_review_accounting"] = {
        "completed_chunks": list(controller_result.get("completed_chunk_ids") or []),
        "requires_human_review_before_next_batch": True,
        "auto_resume_allowed": False,
        "max_chunks_per_batch": 3,
    }
    report["cross_source_reference_visibility"] = {
        "binance_available_reference_count": binance_reference.get("available_reference_count"),
        "reference_only": True,
        "primary_cache_mutated_by_reference": False,
        "normal_backtest_gate_changed_by_reference": False,
    }
    report["quality_gate_matrix"]["chunk_batch_review"] = "required_before_next_bounded_fetch_sprint"
    report["walk_forward_oos_holdout_schema"]["holdout_freeze_before_human_review"] = True
    report["fill_realism_hooks"]["requires_real_fill_evidence_before_live_learning"] = True
    report["anti_overfit_guardrails"]["no_learning_to_execution_bridge"] = True
    report["normal_vs_exploratory_gate"] = {
        "normal_backtests_require_primary_coinbase_quality": True,
        "exploratory_only_can_use_warning_datasets": True,
        "exploratory_only_creates_parameter_evidence": False,
        "secondary_reference_can_release_normal_backtests": False,
    }
    report["hard_gate"]["learning_to_execution_enabled"] = False
    report["hard_gate"]["parameter_evidence_created"] = False
    return {**report, **safety_flags()}


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v11",
    "build_open_source_backlearning_pattern_map_v9",
    "safety_flags",
]
