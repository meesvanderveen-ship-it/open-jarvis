from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


def build_backlearning_data_contracts_v12(*, quality_summary: Dict[str, Any], known_gap_decision: Dict[str, Any]) -> Dict[str, Any]:
    quality_rows = list(quality_summary.get("rows") or [])
    btc_1h = next((row for row in quality_rows if row.get("product_id") == "BTC-USDC" and row.get("timeframe") == "1H"), {})
    classification = known_gap_decision.get("classification")
    primary_clean = btc_1h.get("quality_class") == "good"
    primary_known_gap = classification == "confirmed_coinbase_data_hole_candidate"
    return {
        "generated_at": now_iso(),
        "phase": "D6_backlearning_data_contracts_v12",
        "report_name": "backlearning_data_contracts_v12",
        "status": "backlearning_data_contracts_v12_ready",
        "dataset_contracts": {
            "BTC-USDC:1H": {
                "primary_source": "coinbase_public_candles",
                "primary_clean": primary_clean,
                "primary_known_gap": primary_known_gap,
                "secondary_reference_available": bool(known_gap_decision.get("binance_reference_paths")),
                "normal_backtest_blocked": not primary_clean,
                "exploratory_only_allowed": bool(known_gap_decision.get("exploratory_only_allowed")),
                "creates_parameter_evidence": False,
                "learning_to_execution_enabled": False,
            },
            "BTC-USDC:4H": {
                "primary_source": "coinbase_public_candles",
                "primary_clean": False,
                "primary_known_gap": True,
                "normal_backtest_blocked": True,
                "exploratory_only_allowed": True,
                "creates_parameter_evidence": False,
            },
        },
        "normal_vs_exploratory_gate": {
            "normal_requires_primary_coinbase_good": True,
            "secondary_reference_cannot_release_normal": True,
            "exploratory_creates_parameter_evidence": False,
        },
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "state_write_performed": False,
        "live_order_action_performed": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


__all__ = ["build_backlearning_data_contracts_v12"]
