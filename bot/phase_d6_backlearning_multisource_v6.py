from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_backlearning_multisource_scaffold_v6"


def safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "parameter_evidence_created": False,
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "live_order_action_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
        "coinbase_account_or_order_call_performed": False,
        "binance_account_or_order_call_performed": False,
        "binance_trading_endpoint_call_performed": False,
        "external_candle_written_as_coinbase_candle": False,
        "normal_backtest_released_from_secondary_source": False,
        "state_write_performed": False,
    }


def _sha256(path: str | Path) -> str:
    safe = assert_research_path(path)
    if not safe.exists() or not safe.is_file():
        return ""
    digest = hashlib.sha256()
    with safe.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_open_source_backlearning_pattern_map_v4() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "open_source_backlearning_pattern_map_v4",
        "status": "open_source_backlearning_pattern_map_v4_ready",
        "pattern_only_sources": [
            {
                "project": "Freqtrade",
                "patterns": [
                    "data_download_backtest_and_hyperopt_governance_are_separate",
                    "data_refresh_can_be_incremental_but_must_not_imply_strategy_review",
                ],
            },
            {
                "project": "CCXT",
                "patterns": [
                    "rate_limit_budget_is_exchange_specific",
                    "ohlcv_pagination_must_expect_exchange_data_holes",
                    "retry_budget_should_fail_closed",
                ],
            },
            {
                "project": "vectorbt",
                "patterns": [
                    "vectorized_metric_plumbing_is_research_only",
                    "batch_metrics_do_not_create_runtime_decisions",
                ],
            },
            {
                "project": "Hummingbot",
                "patterns": [
                    "controller_executor_separation",
                    "market_data_state_and_order_lifecycle_state_are_separate",
                ],
            },
        ],
        "rejected_actions": [
            "dependency_install",
            "code_copy",
            "framework_migration",
            "runtime_parameter_mutation",
            "automatic_learning_to_runtime_bridge",
        ],
        **safety_flags(),
    }


def _source_hashes(paths: Iterable[str | Path]) -> List[Dict[str, str]]:
    rows = []
    for raw in paths:
        safe = assert_research_path(raw)
        rows.append({"path": str(safe), "sha256": _sha256(safe)})
    return rows


def build_backlearning_multisource_scaffold_v6(
    *,
    quality_summary: Dict[str, Any],
    controller_result: Dict[str, Any],
    binance_reference: Dict[str, Any],
    source_paths: Iterable[str | Path],
) -> Dict[str, Any]:
    counters = dict(quality_summary.get("global_counters") or {})
    primary_poor = int(counters.get("poor_count") or 0) > 0
    primary_warning = int(counters.get("warning_count") or 0) > 0
    primary_invalid = int(counters.get("invalid_count") or 0) > 0
    primary_good_all = not primary_poor and not primary_warning and not primary_invalid
    secondary_available = int(binance_reference.get("available_reference_count") or 0) > 0
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_multisource_scaffold_v6",
        "status": "backlearning_multisource_scaffold_v6_ready",
        "dataset_contracts": {
            "primary": {
                "source": "coinbase",
                "venue": "coinbase_spot",
                "required_for_normal_backtest": True,
                "must_pass_quality_without_secondary_override": True,
            },
            "secondary": {
                "source": "binance",
                "venue": "binance_spot",
                "reference_only": True,
                "may_fill_primary_cache": False,
                "may_release_normal_backtests": False,
            },
        },
        "dataset_provenance_hashes": _source_hashes(source_paths),
        "quality_gate_matrix": [
            {
                "case": "primary_good",
                "condition_met": bool(primary_good_all),
                "exploratory_only_allowed": True,
                "normal_blocked": not bool(primary_good_all),
            },
            {
                "case": "primary_known_gap_preview",
                "condition_met": True,
                "exploratory_only_allowed": True,
                "normal_blocked": True,
            },
            {
                "case": "primary_poor",
                "condition_met": bool(primary_poor),
                "exploratory_only_allowed": True,
                "normal_blocked": True,
            },
            {
                "case": "secondary_reference_available",
                "condition_met": bool(secondary_available),
                "exploratory_only_allowed": bool(secondary_available),
                "normal_blocked": True,
            },
        ],
        "walk_forward_oos_holdout_schema": {
            "chronological_split_required": True,
            "holdout_label_required": True,
            "source_mix_label_required": True,
            "no_holdout_peeking": True,
        },
        "trial_accounting": {
            "trial_id_required": True,
            "dataset_hash_snapshot_required": True,
            "source_mix_required": True,
            "controller_result_status": controller_result.get("status"),
            "cost_model_snapshot_required": True,
        },
        "cost_aware_metrics_placeholder": [
            "net_return_after_fees",
            "turnover",
            "drawdown",
            "exposure",
            "trade_count",
            "time_in_market",
        ],
        "fill_realism_hooks": {
            "fees_required": True,
            "slippage_required": True,
            "latency_required": True,
            "coinbase_fill_assumptions_required": True,
            "secondary_venue_fill_assumptions_disallowed_for_coinbase_execution": True,
        },
        "parameter_candidate_registry": {
            "registry_schema_allowed": True,
            "search_execution_allowed": False,
            "ranking_allowed": False,
            "runtime_mutation_allowed": False,
            "human_review_required": True,
        },
        "anti_overfit_guardrails": [
            "trial_count_visible",
            "oos_degradation_required_before_review",
            "dataset_warnings_visible",
            "source_mix_visible",
            "cost_model_visible",
            "holdout_lock",
        ],
        "human_review_checklist": [
            "verify_primary_coinbase_quality_snapshot",
            "verify_secondary_reference_is_not_primary_cache",
            "verify_dataset_hashes",
            "verify_no_runtime_mutation",
            "verify_oos_and_holdout_labels",
        ],
        "hard_gate": {
            "learning_to_execution_enabled": False,
            "runtime_parameter_mutation_allowed": False,
            "future_separate_ack_required": True,
        },
        "blockers": ["normal_backtests_deferred_until_primary_coinbase_quality_passes"] if not primary_good_all else [],
        **safety_flags(),
    }


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v6",
    "build_open_source_backlearning_pattern_map_v4",
    "safety_flags",
]
