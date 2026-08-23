from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_backlearning_scaffold_v2"


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


def build_open_source_backlearning_architecture_v2() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "open_source_backlearning_architecture_v2",
        "status": "open_source_backlearning_architecture_v2_ready",
        "sources": [
            {
                "project": "Freqtrade",
                "urls": [
                    "https://docs.freqtrade.io/en/stable/data-download/",
                    "https://docs.freqtrade.io/en/stable/backtesting/",
                    "https://docs.freqtrade.io/en/stable/hyperopt/",
                ],
                "pattern_only_takeaways": [
                    "data_download_is_separate_from_backtesting",
                    "backtesting_requires_local_historical_data",
                    "optimization_is_a_distinct_mode_with_separate_governance",
                ],
            },
            {
                "project": "CCXT",
                "urls": ["https://github.com/ccxt/ccxt/wiki/manual"],
                "pattern_only_takeaways": [
                    "rate_limit_is_an_exchange_client_concern",
                    "paginated_ohlcv_fetches_need_explicit_bounds",
                    "exchange_specific_data_holes_must_be_expected",
                ],
            },
            {
                "project": "vectorbt",
                "urls": ["https://vectorbt.dev/"],
                "pattern_only_takeaways": [
                    "vectorized_metrics_are_useful_for_batch_research",
                    "parameter_grids_are_research_artifacts_not_runtime_approvals",
                    "portfolio_metrics_should_remain_separate_from_execution",
                ],
            },
            {
                "project": "Hummingbot",
                "urls": [
                    "https://hummingbot.org/strategies/v2-strategies/controllers/",
                    "https://hummingbot.org/strategies/v2-strategies/executors/",
                ],
                "pattern_only_takeaways": [
                    "controllers_should_be_separated_from_executors",
                    "market_data_lifecycle_and_order_lifecycle_are_distinct",
                    "execution_boundaries_should_fail_closed",
                ],
            },
        ],
        "architecture_layers": [
            {
                "layer": "data_layer",
                "responsibility": "bounded public candle ingest, candidate roots, rate limits, retry budgets, manifests",
                "v16_policy": "fetch_only_public_market_data_under_research_ack",
            },
            {
                "layer": "dataset_quality_layer",
                "responsibility": "gap detection, staleness, invalid rows, exact candidate coverage before merge",
                "v16_policy": "block_backtests_when_quality_is_poor_or_warning_for_required_scope",
            },
            {
                "layer": "backtest_layer",
                "responsibility": "exploratory-only cached baseline plumbing with costs and fill realism hooks",
                "v16_policy": "no_strategy_or_parameter_claims",
            },
            {
                "layer": "trial_accounting_layer",
                "responsibility": "record planned vs executed trials, input hashes, costs, labels and blockers",
                "v16_policy": "count_trials_without_ranking_or_approval",
            },
            {
                "layer": "walk_forward_oos_layer",
                "responsibility": "chronological train/validation/test labels and holdout protection",
                "v16_policy": "labels_only_until_dataset_quality_is_good",
            },
            {
                "layer": "parameter_candidate_layer",
                "responsibility": "registry of candidate dimensions for human review",
                "v16_policy": "candidate_registry_is_not_parameter_evidence_or_approval",
            },
            {
                "layer": "human_review_layer",
                "responsibility": "explicit review checklist and no-go boundaries",
                "v16_policy": "separate future prompt_required_for_any_parameter_review",
            },
            {
                "layer": "learning_to_execution_gate",
                "responsibility": "prevent research output from changing runtime behavior",
                "v16_policy": "hard_disabled",
            },
        ],
        "rejected_actions": [
            "dependency_install",
            "code_copy",
            "framework_migration",
            "parameter_search_execution",
            "parameter_approval",
            "runtime_config_mutation",
            "learning_to_execution_bridge",
        ],
        **safety_flags(),
        "state_write_performed": False,
    }


def build_backlearning_scaffold_v2(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    quality_ready = bool(summary.get("good_count") == summary.get("quality_report_count") and summary.get("quality_report_count"))
    blockers = []
    if not quality_ready:
        blockers.append("dataset_quality_not_ready_for_normal_backtests")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_scaffold_v2",
        "status": "backlearning_scaffold_v2_ready",
        "dataset_quality_gate": {
            "quality_summary": summary,
            "normal_backtests_allowed": False,
            "exploratory_only_allowed": quality_ready,
            "blockers": blockers,
        },
        "exploratory_only_mode": {
            "enabled_for_v16": False,
            "requires_cached_data_only": True,
            "requires_no_gap_required_scope": True,
            "creates_parameter_evidence": False,
        },
        "walk_forward_oos_layer": {
            "split_modes": ["holdout", "rolling", "expanding"],
            "labels": ["train", "validation", "test"],
            "lookahead_policy": "chronological_only_no_peeking",
        },
        "trial_accounting_layer": {
            "record_input_hashes": True,
            "record_trial_intent": True,
            "record_executed_trials": True,
            "ranking_allowed": False,
        },
        "metrics_layer": {
            "cost_aware_metrics": ["net_return", "fees_quote", "drawdown", "exposure"],
            "fill_realism_hooks": ["post_only_model", "slippage_model", "latency_model"],
            "batch_metrics_allowed": True,
        },
        "parameter_candidate_registry": {
            "registry_allowed": True,
            "parameter_search_performed": False,
            "parameter_review_approved": False,
            "parameter_values_changed": False,
        },
        "human_review_gate": {
            "required_before_parameter_review": True,
            "required_before_runtime_change": True,
            "learning_to_execution_enabled": False,
        },
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "PHASE",
    "build_backlearning_scaffold_v2",
    "build_open_source_backlearning_architecture_v2",
    "safety_flags",
]
