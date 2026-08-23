from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import now_iso


D6_PARAMETER_INVENTORY_PHASE = "D6_parameter_candidate_inventory_v1"


CATEGORY_LABELS = {
    "universe_market_selection": "A. Universe / market selection",
    "market_data_features": "B. Market-data / feature parameters",
    "gatekeeper_routing": "C. Gatekeeper / analysis routing",
    "entry_signal": "D. Entry signal parameters",
    "position_sizing_risk": "E. Position sizing / risk parameters",
    "d2_position_executor": "F. D.2 position executor parameters",
    "d3_controlled_exit": "G. D.3 controlled exit parameters",
    "d4_dynamic_order_management": "H. D.4 dynamic order management",
    "d5_execution_learning": "I. D.5 execution learning metrics",
    "ai_prompt_judge": "J. AI / prompt / judge parameters",
}


SAFETY_CLASSES = {
    "research_only_candidate",
    "human_review_required",
    "high_risk_manual_only",
    "never_auto_change",
}


@dataclass(frozen=True)
class ParameterCandidate:
    parameter_name: str
    category: str
    source_file: str
    source_symbol: str
    default_value: str
    parameter_type: str
    safety_class: str
    evidence_source_needed: List[str]
    eligible_for_future_review: bool
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        if self.category not in CATEGORY_LABELS:
            raise ValueError(f"unknown_parameter_category:{self.category}")
        if self.safety_class not in SAFETY_CLASSES:
            raise ValueError(f"unknown_safety_class:{self.safety_class}")
        return {
            "parameter_name": self.parameter_name,
            "category": self.category,
            "category_label": CATEGORY_LABELS[self.category],
            "source_file": self.source_file,
            "source_symbol": self.source_symbol,
            "default_value": self.default_value,
            "parameter_type": self.parameter_type,
            "safety_class": self.safety_class,
            "evidence_source_needed": list(self.evidence_source_needed),
            "eligible_for_future_review": bool(self.eligible_for_future_review),
            "parameter_change_allowed": False,
            "notes": self.notes,
        }


def _candidate(
    parameter_name: str,
    category: str,
    source_file: str,
    source_symbol: str,
    default_value: str,
    parameter_type: str,
    safety_class: str,
    evidence_source_needed: Iterable[str],
    eligible_for_future_review: bool = True,
    notes: str = "",
) -> ParameterCandidate:
    return ParameterCandidate(
        parameter_name=parameter_name,
        category=category,
        source_file=source_file,
        source_symbol=source_symbol,
        default_value=default_value,
        parameter_type=parameter_type,
        safety_class=safety_class,
        evidence_source_needed=list(evidence_source_needed),
        eligible_for_future_review=eligible_for_future_review,
        notes=notes,
    )


def _safety_flags() -> Dict[str, bool]:
    return {
        "research_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "parameter_search_performed": False,
        "parameter_change_allowed": False,
        "learning_to_execution_allowed": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "runtime_config_mutation_allowed": False,
        "strategy_parameter_mutation_allowed": False,
        "human_review_required": True,
        "parameter_review_approved": False,
    }


def build_parameter_candidates() -> List[Dict[str, Any]]:
    entries = [
        _candidate("allowed_tickers", "universe_market_selection", "bot/config.py", "ALLOWED_TICKERS", "BTC-USDC,...,UNI-USDC", "list[str]", "human_review_required", ["data_coverage_inventory", "dataset_quality_aggregate", "liquidity_spread_reports"]),
        _candidate("primary_interval_hours", "universe_market_selection", "bot/config.py", "PRIMARY_INTERVAL_HOURS", "4", "int", "human_review_required", ["walk_forward_splits", "multi_timeframe_backtests"]),
        _candidate("d6_supported_timeframes", "universe_market_selection", "bot/phase_d6_data_coverage.py", "D6_SUPPORTED_TIMEFRAMES", "15M,1H,4H,1D", "list[str]", "research_only_candidate", ["data_coverage_inventory", "dataset_quality_report"]),
        _candidate("d6_default_years", "universe_market_selection", "bot/phase_d6_data_coverage.py", "D6_DEFAULT_YEARS", "3,5", "list[int]", "research_only_candidate", ["coverage_class_report", "regime_stress_report"]),
        _candidate("granularity_map", "universe_market_selection", "bot/market_data.py", "GRANULARITY_MAP", "15M,1H,4H,1D", "dict[str,str]", "human_review_required", ["candle_ingest_quality", "timeframe_alignment_tests"]),
        _candidate("ema_windows", "market_data_features", "bot/market_data.py", "ema_20,ema_50,ema_200", "20,50,200", "indicator_window", "human_review_required", ["fixed_signal_backtests", "walk_forward_validation", "regime_segmentation"]),
        _candidate("rsi_period", "market_data_features", "bot/market_data.py", "rsi_14", "14", "indicator_window", "human_review_required", ["feature_stability_report", "entry_signal_evidence"]),
        _candidate("rsi_thresholds", "market_data_features", "bot/market_data.py", "1h/4h oversold/overbought flags", "35,70", "threshold", "human_review_required", ["entry_signal_evidence", "regime_segmentation"]),
        _candidate("adx_period", "market_data_features", "bot/market_data.py", "adx_14", "14", "indicator_window", "human_review_required", ["feature_stability_report", "trend_regime_report"]),
        _candidate("adx_strength_threshold", "market_data_features", "bot/market_data.py", "adx strong flags", "25", "threshold", "human_review_required", ["regime_segmentation", "walk_forward_validation"]),
        _candidate("bollinger_band_settings", "market_data_features", "bot/market_data.py", "bollinger_bands(close,20,2.0)", "20,2.0", "indicator_window", "human_review_required", ["feature_stability_report", "mean_reversion_signal_report"]),
        _candidate("compression_threshold", "market_data_features", "bot/market_data.py", "bb_width_pct compression", "0.05", "threshold", "human_review_required", ["regime_segmentation", "fixed_signal_backtests"]),
        _candidate("donchian_lookbacks", "market_data_features", "bot/market_data.py", "donchian_20,donchian_55", "20,55", "indicator_window", "human_review_required", ["breakout_signal_report", "walk_forward_validation"]),
        _candidate("orderbook_depth_imbalance_thresholds", "market_data_features", "bot/market_data.py", "book_pressure", "-0.15,0.15", "threshold", "human_review_required", ["cached_orderbook_snapshots", "fill_realism_report"]),
        _candidate("max_spread_pct", "market_data_features", "bot/config.py", "MAX_SPREAD_PCT", "0.0100", "decimal_pct", "human_review_required", ["spread_distribution_report", "execution_quality_report"]),
        _candidate("cooldown_minutes", "gatekeeper_routing", "bot/config.py", "COOLDOWN_MINUTES", "240", "int_minutes", "human_review_required", ["decision_outcome_logs", "overtrading_analysis"]),
        _candidate("max_candidates_for_deep_analysis", "gatekeeper_routing", "bot/config.py", "MAX_CANDIDATES_FOR_DEEP_ANALYSIS", "5", "int", "human_review_required", ["routing_calibration_pack", "cost_report"]),
        _candidate("max_candidates_for_deepseek_gate", "gatekeeper_routing", "bot/config.py", "MAX_CANDIDATES_FOR_DEEPSEEK_GATE", "10", "int", "human_review_required", ["routing_calibration_pack", "provider_cost_report"]),
        _candidate("max_priority_candidates", "gatekeeper_routing", "bot/config.py", "MAX_PRIORITY_CANDIDATES", "3", "int", "human_review_required", ["routing_calibration_pack"]),
        _candidate("breadth_relaxation_min_tickers", "gatekeeper_routing", "bot/config.py", "BREADTH_RELAXATION_MIN_TICKERS", "3", "int", "human_review_required", ["market_breadth_backtests", "regime_segmentation"]),
        _candidate("watch_promotion_memory_cycles", "gatekeeper_routing", "bot/config.py", "WATCH_PROMOTION_MEMORY_CYCLES", "2", "int_cycles", "human_review_required", ["decision_outcome_logs", "pending_intent_analysis"]),
        _candidate("pending_trade_plan_min_confidence", "gatekeeper_routing", "bot/config.py", "PENDING_TRADE_PLAN_MIN_CONFIDENCE", "60", "int_score", "human_review_required", ["pending_plan_outcomes", "walk_forward_validation"]),
        _candidate("pending_trade_plan_trigger_score", "gatekeeper_routing", "bot/config.py", "PENDING_TRADE_PLAN_TRIGGER_SCORE", "88", "int_score", "human_review_required", ["pending_plan_outcomes", "missed_entry_analysis"]),
        _candidate("pending_trade_plan_max_chase_distance_pct", "entry_signal", "bot/config.py", "PENDING_TRADE_PLAN_MAX_CHASE_DISTANCE_PCT", "0.0200", "decimal_pct", "human_review_required", ["entry_signal_evidence", "missed_fill_analysis"]),
        _candidate("decision_outcome_horizons_hours", "entry_signal", "bot/config.py", "DECISION_OUTCOME_HORIZONS_HOURS", "4,12,24", "csv[int_hours]", "research_only_candidate", ["decision_outcome_logs", "path_outcome_reports"]),
        _candidate("decision_outcome_min_move_pct", "entry_signal", "bot/config.py", "DECISION_OUTCOME_MIN_MOVE_PCT", "0.0250", "decimal_pct", "human_review_required", ["decision_outcome_logs", "fixed_signal_backtests"]),
        _candidate("decision_outcome_adverse_move_pct", "entry_signal", "bot/config.py", "DECISION_OUTCOME_ADVERSE_MOVE_PCT", "0.0200", "decimal_pct", "human_review_required", ["decision_outcome_logs", "drawdown_path_analysis"]),
        _candidate("default_quote_size_usdc", "position_sizing_risk", "bot/config.py", "DEFAULT_QUOTE_SIZE_USDC", "10.00", "decimal_quote", "high_risk_manual_only", ["sizing_sensitivity_pack", "drawdown_analysis", "portfolio_exposure_report"]),
        _candidate("max_notional_usd", "position_sizing_risk", "bot/config.py", "MAX_NOTIONAL_USD", "25.00", "decimal_quote", "high_risk_manual_only", ["sizing_sensitivity_pack", "risk_tail_report"]),
        _candidate("max_open_positions", "position_sizing_risk", "bot/config.py", "MAX_OPEN_POSITIONS", "3", "int", "high_risk_manual_only", ["portfolio_exposure_report", "correlation_regime_report"]),
        _candidate("max_daily_loss_usdc", "position_sizing_risk", "bot/config.py", "MAX_DAILY_LOSS_USDC", "30.00", "decimal_quote", "never_auto_change", ["risk_tail_report", "human_risk_review"]),
        _candidate("allow_averaging_down", "position_sizing_risk", "bot/config.py", "ALLOW_AVERAGING_DOWN", "false", "bool", "never_auto_change", ["loss_cluster_analysis", "human_risk_review"], False),
        _candidate("phase_d2_min_expected_net_edge_pct", "d2_position_executor", "bot/config.py", "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "0.0125", "decimal_pct", "human_review_required", ["cost_aware_backtests", "exit_plan_pack"]),
        _candidate("phase_d2_min_reward_to_fee_ratio", "d2_position_executor", "bot/config.py", "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "3.0", "decimal_ratio", "human_review_required", ["cost_sensitivity_report", "exit_plan_pack"]),
        _candidate("phase_d2_min_reward_to_risk_ratio", "d2_position_executor", "bot/config.py", "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "1.5", "decimal_ratio", "human_review_required", ["drawdown_path_analysis", "exit_plan_pack"]),
        _candidate("phase_d2_fee_cost_model", "d2_position_executor", "bot/phase_d2_position_executor.py", "build_fee_cost_model", "entry_fee=0.0040,exit_fee=0.0040,spread_slippage=0.0020,buffer=0.0025", "cost_model", "human_review_required", ["fee_slippage_assumption_pack", "d5_execution_metrics"]),
        _candidate("phase_d2_default_time_limit_hours", "d2_position_executor", "bot/config.py", "PHASE_D2_DEFAULT_TIME_LIMIT_HOURS", "48", "int_hours", "human_review_required", ["time_in_trade_analysis", "walk_forward_validation"]),
        _candidate("phase_d2_default_trailing_activation_pct", "d2_position_executor", "bot/config.py", "PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT", "0.0250", "decimal_pct", "human_review_required", ["trailing_path_simulation", "d5_execution_logs"]),
        _candidate("phase_d2_default_trailing_distance_pct", "d2_position_executor", "bot/config.py", "PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT", "0.0180", "decimal_pct", "human_review_required", ["trailing_path_simulation", "drawdown_path_analysis"]),
        _candidate("phase_d2_exit_slices", "d2_position_executor", "bot/phase_d2_position_executor.py", "_fallback_exit_slices", "TP1=0.50,TP2=0.25,RUNNER=0.25; fallback 0.70/0.30 or TP_CLOSE=1.00", "allocation", "human_review_required", ["exit_plan_pack", "min_size_fallback_report"]),
        _candidate("phase_d2_allow_averaging_down", "d2_position_executor", "bot/config.py", "PHASE_D2_ALLOW_AVERAGING_DOWN", "false", "bool", "never_auto_change", ["loss_cluster_analysis", "human_risk_review"], False),
        _candidate("phase_d3_max_exit_order_quote", "d3_controlled_exit", "bot/config.py", "PHASE_D3_MAX_EXIT_ORDER_QUOTE", "25.00", "decimal_quote", "high_risk_manual_only", ["controlled_exit_safety_pack", "risk_review"]),
        _candidate("phase_d3_max_open_exit_orders", "d3_controlled_exit", "bot/config.py", "PHASE_D3_MAX_OPEN_EXIT_ORDERS", "4", "int", "high_risk_manual_only", ["duplicate_exit_analysis", "reservation_drift_report"]),
        _candidate("phase_d3_max_new_exit_orders_per_cycle", "d3_controlled_exit", "bot/config.py", "PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE", "1", "int", "never_auto_change", ["retry_storm_safety_review"], False),
        _candidate("phase_d3_exit_order_post_only", "d3_controlled_exit", "bot/config.py", "PHASE_D3_EXIT_ORDER_POST_ONLY", "true", "bool", "high_risk_manual_only", ["fill_realism_report", "fee_slippage_assumption_pack"]),
        _candidate("phase_d3_require_reduce_only_local", "d3_controlled_exit", "bot/config.py", "PHASE_D3_REQUIRE_REDUCE_ONLY_LOCAL", "true", "bool", "never_auto_change", ["p0_safety_review"], False),
        _candidate("d3_open_statuses", "d3_controlled_exit", "bot/phase_d3_controlled_live_exits.py", "D3_OPEN_STATUSES", "planned,pending,submitted,partially_filled,cancel_pending,replace_pending,open,active,new,queued", "set[str]", "never_auto_change", ["lifecycle_fixture_tests", "p0_safety_review"], False),
        _candidate("d4_activation_pct", "d4_dynamic_order_management", "bot/phase_d4_trailing_preview.py", "policy.activation_pct", "caller_supplied", "decimal_pct", "human_review_required", ["trailing_path_simulation", "walk_forward_validation"]),
        _candidate("d4_trailing_distance_pct", "d4_dynamic_order_management", "bot/phase_d4_trailing_preview.py", "policy.trailing_distance_pct", "caller_supplied", "decimal_pct", "human_review_required", ["trailing_path_simulation", "d5_execution_logs"]),
        _candidate("d4_refresh_tolerance_pct", "d4_dynamic_order_management", "bot/phase_d4_trailing_preview.py", "policy.refresh_tolerance_pct", "caller_supplied", "decimal_pct", "human_review_required", ["cancel_replace_churn_report", "fill_realism_report"]),
        _candidate("d4_stale_book_seconds", "d4_dynamic_order_management", "bot/phase_d4_trailing_preview.py", "policy.stale_book_seconds", "caller_supplied", "int_seconds", "human_review_required", ["cached_orderbook_snapshots", "fill_realism_report"]),
        _candidate("d4_cooldown_seconds", "d4_dynamic_order_management", "bot/phase_d4_trailing_preview.py", "policy.cooldown_seconds", "caller_supplied", "int_seconds", "human_review_required", ["cancel_replace_latency_report", "retry_storm_safety_review"]),
        _candidate("max_order_replaces_per_ticker_per_hour", "d4_dynamic_order_management", "bot/config.py", "MAX_ORDER_REPLACES_PER_TICKER_PER_HOUR", "1", "int", "never_auto_change", ["cancel_replace_churn_report", "p0_safety_review"], False),
        _candidate("d5_target_distance_bands", "d5_execution_learning", "bot/phase_d5_execution_metrics.py", "_target_distance_band", "near<=0.01,approaching<=0.03,far>0.03", "threshold_set", "research_only_candidate", ["d5_execution_logs", "no_fill_analysis"]),
        _candidate("d5_no_fill_reprice_age", "d5_execution_learning", "bot/phase_d5_execution_metrics.py", "_no_fill_recommendation_label", "21600 seconds", "int_seconds", "research_only_candidate", ["no_fill_duration_report", "d45_historical_reports"]),
        _candidate("d5_learning_log_schema_version", "d5_execution_learning", "bot/phase_d5_learning_log.py", "D5_LEARNING_LOG_SCHEMA_VERSION", "1.0", "schema_version", "never_auto_change", ["schema_compatibility_tests"], False),
        _candidate("trade_reflection_min_samples_for_signal", "d5_execution_learning", "bot/config.py", "TRADE_REFLECTION_MIN_SAMPLES_FOR_SIGNAL", "3", "int", "human_review_required", ["trade_reflection_analytics", "sample_size_report"]),
        _candidate("trade_reflection_recent_limit", "d5_execution_learning", "bot/config.py", "TRADE_REFLECTION_RECENT_LIMIT", "12", "int", "research_only_candidate", ["trade_reflection_analytics"]),
        _candidate("enable_expensive_judge_gate", "ai_prompt_judge", "bot/config.py", "ENABLE_EXPENSIVE_JUDGE_GATE", "true", "bool", "high_risk_manual_only", ["routing_calibration_pack", "provider_cost_report"]),
        _candidate("judge_min_gate_confidence", "ai_prompt_judge", "bot/config.py", "JUDGE_MIN_GATE_CONFIDENCE", "62", "int_score", "high_risk_manual_only", ["routing_calibration_pack", "decision_outcome_logs"]),
        _candidate("judge_min_synth_confidence", "ai_prompt_judge", "bot/config.py", "JUDGE_MIN_SYNTH_CONFIDENCE", "60", "int_score", "high_risk_manual_only", ["routing_calibration_pack", "decision_outcome_logs"]),
        _candidate("judge_min_bull_score", "ai_prompt_judge", "bot/config.py", "JUDGE_MIN_BULL_SCORE", "56", "int_score", "high_risk_manual_only", ["routing_calibration_pack", "decision_outcome_logs"]),
        _candidate("judge_max_bear_score", "ai_prompt_judge", "bot/config.py", "JUDGE_MAX_BEAR_SCORE", "72", "int_score", "high_risk_manual_only", ["routing_calibration_pack", "decision_outcome_logs"]),
        _candidate("reject_unknown_llm_keys", "ai_prompt_judge", "bot/config.py", "REJECT_UNKNOWN_LLM_KEYS", "true", "bool", "never_auto_change", ["schema_failure_report", "prompt_safety_review"], False),
        _candidate("openai_model_selection", "ai_prompt_judge", "bot/config.py", "OPENAI_MODEL/OPENAI_JUDGE_MODEL/OPENAI_TRADE_PLANNER_MODEL/OPENAI_EXECUTION_PLANNER_MODEL", "env/default model names", "model_name", "never_auto_change", ["provider_quality_report", "human_prompt_review"], False),
        _candidate("live_execution_flags", "ai_prompt_judge", "bot/config.py", "ENABLE_LIVE_EXIT_ORDERS,ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT,AUTONOMOUS_ALLOW_EXITS", "disabled unless explicitly armed", "bool_flags", "never_auto_change", ["p0_safety_review"], False),
    ]
    return [entry.to_dict() for entry in entries]


def build_phase_d6_parameter_inventory_report(*, categories: Iterable[str] | None = None) -> Dict[str, Any]:
    selected_categories = [str(c).strip() for c in categories or [] if str(c).strip()]
    unknown = [c for c in selected_categories if c not in CATEGORY_LABELS]
    if unknown:
        raise ValueError(f"unsupported_parameter_inventory_category:{','.join(unknown)}")

    candidates = build_parameter_candidates()
    if selected_categories:
        wanted = set(selected_categories)
        candidates = [item for item in candidates if item["category"] in wanted]

    category_counts: Dict[str, int] = {key: 0 for key in CATEGORY_LABELS}
    safety_class_counts: Dict[str, int] = {key: 0 for key in sorted(SAFETY_CLASSES)}
    eligible_count = 0
    for item in candidates:
        category_counts[item["category"]] += 1
        safety_class_counts[item["safety_class"]] += 1
        if item["eligible_for_future_review"]:
            eligible_count += 1

    return {
        "generated_at": now_iso(),
        "phase": D6_PARAMETER_INVENTORY_PHASE,
        "status": "d6_parameter_candidate_inventory_ready",
        "source_scope": [
            "bot/config.py",
            "bot/market_data.py",
            "bot/phase_d2_position_executor.py",
            "bot/phase_d3_controlled_live_exits.py",
            "bot/phase_d4_trailing_preview.py",
            "bot/phase_d5_execution_metrics.py",
            "bot/phase_d5_learning_log.py",
            "existing D.6 modules",
        ],
        "category_labels": dict(CATEGORY_LABELS),
        "categories_filter": selected_categories,
        "candidate_count": len(candidates),
        "eligible_for_future_review_count": eligible_count,
        "category_counts": category_counts,
        "safety_class_counts": safety_class_counts,
        "parameters": candidates,
        "warnings": [
            "inventory_only_not_parameter_ranking",
            "defaults_are_static_source_defaults_when_safely_visible",
            "human_review_required_before_any_parameter_change",
            "no_runtime_config_or_env_loaded",
        ],
        "limitations": [
            "curated_static_inventory_not_exhaustive_ast_analysis",
            "does_not_validate_current_runtime_env_values",
            "does_not_evaluate_parameter_quality",
            "does_not_search_parameter_values",
            "does_not_rank_parameters",
            "does_not_create_parameter_proposals",
        ],
        "prohibited_interpretations": [
            "do_not_infer_parameter_change",
            "do_not_infer_best_parameter",
            "do_not_infer_live_readiness",
            "do_not_use_as_execution_signal",
            "do_not_use_as_parameter_review_approval",
        ],
        **_safety_flags(),
    }


__all__ = [
    "CATEGORY_LABELS",
    "D6_PARAMETER_INVENTORY_PHASE",
    "SAFETY_CLASSES",
    "build_parameter_candidates",
    "build_phase_d6_parameter_inventory_report",
]
