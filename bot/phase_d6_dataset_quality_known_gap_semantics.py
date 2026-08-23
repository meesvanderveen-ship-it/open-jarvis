from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


def build_dataset_quality_known_gap_semantics(*, policy_review: Dict[str, Any]) -> Dict[str, Any]:
    decision = dict(policy_review.get("policy_decision") or {})
    continuation_allowed = bool(decision.get("allows_chunk53_continuation"))
    exploratory_allowed = bool(decision.get("allows_exploratory_only"))
    return {
        "generated_at": now_iso(),
        "phase": "D6_dataset_quality_known_gap_semantics_v1",
        "report_name": "dataset_quality_known_gap_semantics_v1",
        "status": "dataset_quality_known_gap_semantics_v1_ready",
        "raw_coinbase_data_remains_visible_imperfect": True,
        "known_gap_exception_scope": "report_metadata_only",
        "raw_cache_mutation_allowed": False,
        "synthetic_ohlcv_allowed": False,
        "secondary_source_repair_allowed": False,
        "normal_backtest_blocked": True,
        "exploratory_only_allowed_with_warnings": exploratory_allowed,
        "chunk_continuation_allowed_if_downstream_ranges_independently_validate": continuation_allowed,
        "known_gap_metadata": {
            "chunk_id": policy_review.get("chunk_id"),
            "missing_coinbase_starts": list(policy_review.get("missing_coinbase_starts") or []),
            "classification": policy_review.get("classification"),
            "requires_human_ack": decision.get("requires_human_ack"),
            "requires_future_revisit": decision.get("requires_future_revisit"),
        },
        "normal_gate_policy": {
            "normal_requires_primary_coinbase_clean_or_explicit_future_policy": True,
            "this_report_releases_normal_backtests": False,
        },
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "state_write_performed": False,
        "live_order_action_performed": False,
        "coinbase_account_or_order_call_performed": False,
        "binance_account_or_order_call_performed": False,
        "binance_trading_endpoint_call_performed": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "learning_to_execution_enabled": False,
    }


__all__ = ["build_dataset_quality_known_gap_semantics"]
