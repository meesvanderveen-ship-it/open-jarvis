from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_backlearning_scaffold_v4"


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
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "live_order_action_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
        "coinbase_account_or_order_call_performed": False,
    }


def build_open_source_backlearning_pattern_map_v3() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "open_source_backlearning_pattern_map_v3",
        "status": "open_source_backlearning_pattern_map_v3_ready",
        "pattern_only_sources": [
            {
                "project": "Freqtrade",
                "patterns": [
                    "data_refresh_backtest_and_research_modes_are_separate",
                    "missing_data_should_be_explicit_in_timerange_refresh",
                    "protections_are_governance_inputs_not_runtime_shortcuts",
                ],
            },
            {
                "project": "CCXT",
                "patterns": [
                    "client_level_rate_limit_and_enable_rate_limit_concept",
                    "bounded_ohlcv_pagination",
                    "exchange_ohlcv_holes_are_expected_data_quality_events",
                ],
            },
            {
                "project": "vectorbt",
                "patterns": [
                    "vectorized_local_metrics_can_batch_research",
                    "portfolio_analysis_should_stay_separate_from_execution",
                    "parameter_grid_is_a_research_concept_only",
                ],
            },
            {
                "project": "Hummingbot",
                "patterns": [
                    "controller_executor_separation",
                    "market_data_state_and_order_lifecycle_state_are_separate",
                    "execution_boundaries_fail_closed",
                ],
            },
        ],
        "rejected_actions": [
            "dependency_install",
            "code_copy",
            "framework_migration",
            "runtime_parameter_mutation",
            "research_to_runtime_bridge",
        ],
        **safety_flags(),
        "state_write_performed": False,
    }


def build_backlearning_scaffold_v4(*, quality_summary: Dict[str, Any], known_gap_preview: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    known_gap_ok = known_gap_preview.get("gap_class") == "acceptable_known_gap_for_exploratory_research"
    blockers = ["dataset_quality_not_ready_for_normal_backtests"]
    if not known_gap_ok:
        blockers.append("known_gap_preview_not_acceptable_for_exploratory_scope")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_scaffold_v4",
        "status": "backlearning_scaffold_v4_ready",
        "dataset_contract_schema": {
            "required_candle_fields": ["product_id", "timeframe", "start", "open", "high", "low", "close", "volume"],
            "required_metadata": ["source", "fetched_at"],
            "known_gap_annotation_allowed": True,
            "synthetic_ohlcv_allowed": False,
            "raw_cache_mutation_by_annotation_allowed": False,
        },
        "quality_to_backtest_gate": {
            "quality_summary": summary,
            "normal_backtest_allowed": False,
            "exploratory_only_allowed": bool(known_gap_ok),
            "known_gap_preview_status": known_gap_preview.get("status"),
            "known_gap_class": known_gap_preview.get("gap_class"),
        },
        "walk_forward_oos_holdout_schema": {
            "split_order": ["train", "validation", "test"],
            "rolling_supported": True,
            "expanding_supported": True,
            "holdout_may_not_select_runtime_behavior": True,
            "lookahead_policy": "chronological_only_no_peeking",
        },
        "trial_accounting": {
            "trial_id": "required",
            "input_hashes": "required",
            "dataset_quality_snapshot": "required",
            "known_gap_snapshot": "required_when_present",
            "cost_model_snapshot": "required",
            "trial_result_can_only_be_descriptive": True,
        },
        "cost_aware_metrics": {
            "metrics": ["net_return", "fees_quote", "drawdown", "turnover", "exposure", "trade_count", "time_in_market"],
            "batch_metrics_allowed": True,
            "ranking_allowed": False,
        },
        "fill_realism_hooks": {
            "fees": "required",
            "slippage": "required_before_live_comparison",
            "latency": "required_before_live_comparison",
            "post_only_fill_model": "required_before_live_comparison",
        },
        "parameter_candidate_registry": {
            "registry_allowed": True,
            "search_execution_allowed": False,
            "ranking_allowed": False,
            "runtime_mutation_allowed": False,
        },
        "anti_overfit_guardrails": [
            "minimum_split_count_before_human_review",
            "oos_degradation_report_required",
            "holdout_lock",
            "trial_count_visible",
            "cost_model_visible",
            "dataset_warnings_visible",
        ],
        "human_review_checklist": [
            "verify_dataset_quality_snapshot",
            "verify_known_gap_annotations",
            "verify_no_runtime_mutation",
            "verify_cost_and_fill_model_assumptions",
            "verify_oos_degradation_before_any_future_review",
        ],
        "execution_gate": {
            "learning_to_execution_enabled": False,
            "runtime_mutation_allowed": False,
            "future_separate_ack_required": True,
        },
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "PHASE",
    "build_backlearning_scaffold_v4",
    "build_open_source_backlearning_pattern_map_v3",
    "safety_flags",
]
