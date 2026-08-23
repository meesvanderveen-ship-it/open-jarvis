from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


RESEARCH_PRIOR_PROFILE_V1: Dict[str, Any] = {
    "phase": "research_prior_parameter_profile_v1",
    "safe_to_live_activate_now": False,
    "requires_backtest": True,
    "requires_operator_review": True,
    "profile_role": "research_prior_not_live_profile",
    "trend_filter": {
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 200,
        "confidence": "medium",
        "source_type": "research_prior_classical_ta_and_crypto_ttr",
    },
    "breakout_filter": {
        "donchian_fast": 20,
        "donchian_slow": 55,
        "confidence": "medium",
        "source_type": "research_prior_trading_range_breakout",
    },
    "adx_thresholds": {
        "trend_candidate": 20,
        "strong_trend": 25,
        "confidence": "medium",
        "source_type": "classical_ta_prior_requires_backtest",
    },
    "volatility_context": {
        "bollinger_period": 20,
        "bollinger_stddev": 2,
        "rsi_period": 14,
        "atr_period": 14,
        "confidence": "medium",
        "source_type": "classical_ta_prior_requires_backtest",
    },
    "entry_strictness": {
        "objective_score_starter_min": {"candidate_band": [0.08, 0.12], "default_candidate": 0.10},
        "objective_score_normal_min": {"candidate_band": [0.12, 0.18], "default_candidate": 0.15},
        "objective_score_strong_min": {"candidate_band": [0.18, 0.25], "default_candidate": 0.22},
        "planner_no_plan_policy": "no_plan_only_with_missing_trigger_missing_invalidation_negative_ev_bad_spread_bad_liquidity_or_chase_risk",
        "confidence": "low_medium",
        "source_type": "passivity_audit_prior_requires_btc_eth_backtest",
    },
    "cost_aware_filters": {
        "max_spread_pct_normal": {"candidate_band": [0.0025, 0.0060], "default_candidate": 0.0060},
        "max_spread_pct_exploration": {"candidate_band": [0.0025, 0.0040], "default_candidate": 0.0040},
        "min_reward_to_fee_ratio_starter": {"candidate_band": [2.0, 2.5], "default_candidate": 2.2},
        "min_reward_to_fee_ratio_normal": {"candidate_band": [2.3, 3.0], "default_candidate": 2.5},
        "min_reward_to_fee_ratio_strong": {"candidate_band": [2.8, 3.5], "default_candidate": 3.0},
        "confidence": "medium",
        "source_type": "cost_aware_execution_prior_requires_fill_validation",
    },
    "reward_risk": {
        "min_reward_to_risk_starter": {"candidate_band": [1.10, 1.30], "default_candidate": 1.20},
        "min_reward_to_risk_normal": {"candidate_band": [1.30, 1.70], "default_candidate": 1.50},
        "min_reward_to_risk_strong": {"candidate_band": [1.70, 2.20], "default_candidate": 1.80},
        "min_expected_net_edge_pct_starter": {"candidate_band": [0.0060, 0.0090], "default_candidate": 0.0080},
        "min_expected_net_edge_pct_normal": {"candidate_band": [0.0090, 0.0125], "default_candidate": 0.0100},
        "min_expected_net_edge_pct_strong": {"candidate_band": [0.0125, 0.0200], "default_candidate": 0.0125},
        "confidence": "low_medium",
        "source_type": "risk_reward_prior_requires_walk_forward",
    },
    "exit_policy": {
        "atr_stop_multiplier_starter": {"candidate_band": [1.2, 1.8], "default_candidate": 1.5},
        "atr_stop_multiplier_normal": {"candidate_band": [1.5, 2.2], "default_candidate": 1.8},
        "atr_stop_multiplier_strong": {"candidate_band": [1.8, 2.8], "default_candidate": 2.2},
        "take_profit_r_multiple_starter": {"candidate_band": [1.3, 2.0], "default_candidate": 1.5},
        "take_profit_r_multiple_normal": {"candidate_band": [1.8, 3.0], "default_candidate": 2.2},
        "exit_target_max_distance_from_mid_pct": {"candidate_band": [0.025, 0.050], "default_candidate": 0.035},
        "partial_exit_min_quote_usdc": 20.00,
        "full_close_exception_allowed": True,
        "confidence": "medium",
        "source_type": "risk_policy_exit_prior_requires_live_validation",
    },
    "order_sizing": {
        "min_live_order_quote_usdc": 20.00,
        "max_live_order_quote_usdc": 100.00,
        "default_quote_size_usdc": 20.00,
        "starter_probe_band_usdc": [20.00, 35.00],
        "normal_entry_band_usdc": [35.00, 60.00],
        "strong_entry_band_usdc": [60.00, 100.00],
        "max_new_orders_per_cycle": 1,
        "max_open_orders": 3,
        "max_open_positions": 3,
        "confidence": "medium",
        "source_type": "risk_policy_position_sizing_prior_requires_live_validation",
    },
    "bounded_exploration": {
        "enabled_by_default": False,
        "min_quote_usdc": 20.00,
        "max_quote_usdc": 35.00,
        "max_open_probes": 1,
        "max_probes_per_day": 2,
        "allowed_tickers": ["BTC-USDC", "ETH-USDC", "SOL-USDC"],
        "allow_market_orders": False,
        "require_hard_risk_green": True,
        "require_fresh_trigger": True,
        "require_no_chase": True,
        "max_spread_pct": 0.0040,
        "require_orderbook_snapshot": True,
        "confidence": "medium",
        "source_type": "bounded_learning_prior_requires_operator_ack",
    },
}


def build_research_prior_parameter_profile(*, generated_at: str | None = None) -> Dict[str, Any]:
    profile = deepcopy(RESEARCH_PRIOR_PROFILE_V1)
    profile["generated_at"] = generated_at or now_iso()
    profile["read_only"] = True
    profile["coinbase_call_attempted"] = False
    profile["state_write_performed"] = False
    profile["env_write_performed"] = False
    profile["approved_profile_written"] = False
    return profile


def research_prior_status(profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = profile or RESEARCH_PRIOR_PROFILE_V1
    return {
        "available": True,
        "safe_to_live_activate_now": bool(data.get("safe_to_live_activate_now")),
        "requires_backtest": bool(data.get("requires_backtest")),
        "requires_operator_review": bool(data.get("requires_operator_review")),
    }


__all__ = ["RESEARCH_PRIOR_PROFILE_V1", "build_research_prior_parameter_profile", "research_prior_status"]
