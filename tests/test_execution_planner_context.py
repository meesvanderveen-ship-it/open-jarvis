from __future__ import annotations

from bot.execution_planner import build_execution_planner_input


def test_execution_planner_input_contains_product_rules_rejections_and_feasibility():
    analysis = {
        "judge": {"decision": "wait", "side": "NONE", "size_quote": "0"},
        "trade_plan": {
            "plan_action": "prepare_reclaim_retest_limit_entry",
            "side": "BUY",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "invalidation_price": "98.00",
            "take_profit_1": "104.00",
            "max_quote_size": "20.00",
        },
        "feature_pack": {
            "ticker": "BTC-USDC",
            "market": {"best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75", "spread_pct": "0.0002"},
            "orderbook_context": {"snapshot_available": True, "best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75"},
            "decision_context": {
                "product_rules": {
                    "product_id": "BTC-USDC",
                    "price_increment": "0.01",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "base_min_size": "0.00000001",
                    "quote_min_size": "1.00",
                },
                "recent_exchange_rejections": [{"ticker": "BTC-USDC", "reject_reason": "INVALID_PRICE_PRECISION"}],
                "execution_feasibility": {
                    "can_construct_valid_limit_buy_payload": True,
                    "normalized_price": "99.75",
                    "normalized_base_size": "0.20050125",
                    "estimated_quote": "19.9999996875",
                    "blockers": [],
                    "warnings": [],
                },
            },
        },
    }
    planner_input = build_execution_planner_input(ticker="BTC-USDC", analysis=analysis)
    assert planner_input["product_rules"]["precision_context_available"] is True
    assert planner_input["recent_exchange_rejections"][0]["reject_reason"] == "INVALID_PRICE_PRECISION"
    assert planner_input["execution_feasibility"]["can_construct_valid_limit_buy_payload"] is True
    assert planner_input["orderbook_entry_preview"]["execution_feasibility"]["can_construct_valid_limit_buy_payload"] is True
