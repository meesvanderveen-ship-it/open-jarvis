from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_backlearning_multisource_scaffold_v5"


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


def build_backlearning_multisource_scaffold_v5(
    *,
    quality_summary: Dict[str, Any],
    multi_source_policy: Dict[str, Any],
    btc_4h_reference: Dict[str, Any],
) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    counters = {
        "good_count": int(summary.get("good_count", 0)),
        "warning_count": int(summary.get("warning_count", 0)),
        "poor_count": int(summary.get("poor_count", 0)),
        "invalid_count": int(summary.get("invalid_count", 0)),
    }
    primary_ready = counters["poor_count"] == 0 and counters["invalid_count"] == 0 and counters["warning_count"] == 0
    secondary_available = (
        btc_4h_reference.get("binance_reference", {}).get("classification") == "external_reference_available"
    )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_multisource_scaffold_v5",
        "status": "backlearning_multisource_scaffold_v5_ready",
        "dataset_contract": {
            "primary_sources": [
                {
                    "source": "coinbase",
                    "venue": "coinbase_spot",
                    "role": "primary_execution_market_dataset",
                    "normal_backtest_required": True,
                    "quality_must_pass_without_secondary_override": True,
                }
            ],
            "secondary_sources": [
                {
                    "source": "binance",
                    "venue": "binance_spot",
                    "role": "secondary_reference_dataset",
                    "allowed_for_gap_diagnostic": True,
                    "allowed_for_exploratory_cross_venue_analysis": True,
                    "normal_backtest_required": False,
                    "may_fill_primary_cache": False,
                }
            ],
            "required_provenance": list(
                (multi_source_policy.get("required_provenance_fields") if multi_source_policy else []) or []
            ),
            "synthetic_ohlcv_allowed": False,
        },
        "quality_gates": {
            "primary_coinbase_quality_snapshot": counters,
            "normal_backtest_gate": {
                "allowed": bool(primary_ready),
                "secondary_source_can_override": False,
                "blockers": [] if primary_ready else ["primary_coinbase_dataset_quality_not_ready"],
            },
            "exploratory_cross_venue_gate": {
                "allowed": bool(secondary_available),
                "requires_warning_labels": True,
                "requires_coinbase_gap_visibility": True,
                "may_create_parameter_evidence": False,
            },
        },
        "walk_forward_oos_trial_accounting": {
            "split_schema_required": True,
            "holdout_labels_required": True,
            "trial_id_required": True,
            "input_hashes_required": True,
            "primary_and_secondary_source_hashes_separate": True,
            "secondary_source_use_must_be_declared_per_trial": True,
        },
        "cost_and_fill_realism": {
            "fees_required": True,
            "slippage_required_before_live_comparison": True,
            "latency_required_before_live_comparison": True,
            "venue_specific_fill_assumptions_required": True,
            "secondary_venue_prices_may_not_stand_in_for_coinbase_fills": True,
        },
        "parameter_candidate_registry": {
            "registry_schema_allowed": True,
            "candidate_requires_human_review": True,
            "search_execution_allowed": False,
            "ranking_allowed": False,
            "runtime_mutation_allowed": False,
        },
        "open_source_pattern_mapping": [
            {
                "project": "Freqtrade",
                "applied_pattern": "separate_data_refresh_backtest_and_research_governance",
            },
            {
                "project": "CCXT",
                "applied_pattern": "exchange_specific_ohlcv_gaps_and_client_rate_limit_concept",
            },
            {
                "project": "vectorbt",
                "applied_pattern": "local_vectorized_metrics_as_analysis_plumbing_only",
            },
            {
                "project": "Hummingbot",
                "applied_pattern": "controller_executor_and_lifecycle_state_separation",
            },
        ],
        "hard_gate": {
            "learning_to_execution_enabled": False,
            "runtime_parameter_mutation_allowed": False,
            "future_separate_ack_required": True,
        },
        "blockers": [] if primary_ready else ["normal_backtests_deferred_until_primary_coinbase_quality_passes"],
        **safety_flags(),
    }


__all__ = [
    "PHASE",
    "build_backlearning_multisource_scaffold_v5",
    "safety_flags",
]
