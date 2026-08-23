from __future__ import annotations

from bot.objective_trade_score import grade_for_score, score_trade_context


def test_objective_trade_score_never_authorizes_live_order() -> None:
    score = score_trade_context(
        {
            "ticker": "BTC-USDC",
            "feature_pack": {
                "market": {"mid_price": "100", "spread_pct": "0.001"},
                "indicators": {"4h": {"adx_14": "25"}, "1h": {"rsi_14": "55"}},
                "microstructure": {"1h": {"volume_vs_avg": "1.3"}},
                "structure": {"nearest_support": "98", "nearest_resistance": "106"},
                "risk_context": {"roundtrip_fee_pct": "0.012"},
                "product_rules": {"base_increment": "0.00000001", "price_increment": "0.01"},
            },
            "trade_plan": {"preferred_limit_price": "100", "stop_loss": "98", "take_profit_1": "106"},
        }
    )

    assert 0 <= score["objective_score"] <= 1
    assert score["grade"] in {"A", "B", "C", "D", "F"}
    assert score["live_order_authority"] is False
    assert score["read_only"] is True


def test_objective_trade_score_blocks_missing_stop_and_target() -> None:
    score = score_trade_context({"feature_pack": {"market": {"mid_price": "100"}}})
    assert "invalidation_or_stop_missing" in score["hard_blockers"]
    assert "target_missing" in score["hard_blockers"]
    assert score["recommended_action"] == "ignore"
    assert grade_for_score(0.8) == "A"
