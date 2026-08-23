from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable

from bot.phase_d6_backlearning_multisource_v9 import (
    build_backlearning_multisource_scaffold_v9,
    build_open_source_backlearning_pattern_map_v7,
    safety_flags,
)
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import now_iso


PHASE = "D6_backlearning_multisource_scaffold_v10"


def _sha256_file(path: str | Path) -> str:
    safe = assert_research_path(path)
    digest = hashlib.sha256()
    if not safe.is_file():
        return ""
    with safe.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_hashes(paths: Iterable[str | Path]) -> Dict[str, str]:
    return {str(assert_research_path(path)): _sha256_file(path) for path in paths}


def build_open_source_backlearning_pattern_map_v8() -> Dict[str, Any]:
    report = build_open_source_backlearning_pattern_map_v7()
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "open_source_backlearning_pattern_map_v8"
    report["status"] = "open_source_backlearning_pattern_map_v8_ready"
    report["v8_additions"] = [
        "dataset_hash_trial_accounting",
        "walk_forward_oos_holdout_schema",
        "cost_aware_metrics_placeholders",
        "fill_realism_hooks",
        "anti_overfit_guardrails",
    ]
    return report


def build_backlearning_multisource_scaffold_v10(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str | Path],
) -> Dict[str, Any]:
    paths = list(source_paths)
    report = build_backlearning_multisource_scaffold_v9(
        quality_summary=quality_summary,
        controller_result=controller_result,
        binance_reference=binance_reference,
        source_paths=paths,
    )
    report["generated_at"] = now_iso()
    report["phase"] = PHASE
    report["report_name"] = "backlearning_multisource_scaffold_v10"
    report["status"] = "backlearning_multisource_scaffold_v10_ready"
    report["source_contracts"] = {
        "primary_source": "coinbase_public_candles",
        "primary_role": "execution_market_research_dataset",
        "secondary_source": "binance_public_klines",
        "secondary_role": "reference_diagnostic_only",
        "secondary_can_mutate_primary_cache": False,
        "secondary_can_release_normal_backtests": False,
    }
    report["dataset_provenance_hashes"] = _dataset_hashes(paths)
    report["quality_gate_matrix"] = {
        "normal_backtests": "blocked_until_primary_coinbase_quality_has_no_warning_poor_invalid_rows",
        "exploratory_only_plumbing": "allowed_with_warning_rows_but_no_parameter_evidence",
        "secondary_reference": "visibility_only_never_quality_gate_release",
        "live_24h": "blocked_until_fresh_preflight_and_exact_live_ack",
    }
    report["trial_accounting_by_dataset_hash_and_source_mix"] = {
        "trial_id_required": True,
        "dataset_hash_required": True,
        "source_mix_required": True,
        "source_mix_values": ["coinbase_only", "coinbase_primary_binance_reference"],
        "creates_parameter_evidence": False,
    }
    report["walk_forward_oos_holdout_schema"] = {
        "walk_forward_windows_required": True,
        "out_of_sample_label_required": True,
        "holdout_untouched_until_review": True,
        "run_now": False,
    }
    report["cost_aware_metrics_placeholders"] = {
        "fees": "placeholder_only",
        "spread": "placeholder_only",
        "slippage": "placeholder_only",
        "latency": "placeholder_only",
        "run_now": False,
    }
    report["fill_realism_hooks"] = {
        "coinbase_fill_evidence_adapter_future": True,
        "no_fill_duration_future": True,
        "cancel_replace_timing_future": True,
        "run_now": False,
    }
    report["anti_overfit_guardrails"] = {
        "no_parameter_search": True,
        "no_ranking": True,
        "no_parameter_mutation": True,
        "human_review_before_any_parameter_task": True,
    }
    report["human_review_checklist"] = [
        "confirm_primary_coinbase_quality_before_normal_backtests",
        "confirm_secondary_reference_did_not_mutate_primary_cache",
        "confirm_dataset_hashes_before_comparing_runs",
        "confirm_no_parameter_evidence_claim",
        "confirm_no_learning_to_execution_bridge",
    ]
    report["normal_vs_exploratory_gate"] = {
        "normal_backtests_require_primary_coinbase_quality": True,
        "exploratory_only_can_use_warning_datasets": True,
        "exploratory_only_creates_parameter_evidence": False,
    }
    report["hard_gate"]["learning_to_execution_enabled"] = False
    report["hard_gate"]["parameter_evidence_created"] = False
    return {**report, **safety_flags()}


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v10",
    "build_open_source_backlearning_pattern_map_v8",
    "safety_flags",
]
