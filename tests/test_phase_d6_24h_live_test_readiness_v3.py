from __future__ import annotations

from bot.phase_d6_multi_ticker_backlearning_readiness import build_24h_live_test_readiness_v3


def test_24h_readiness_v3_blocks_all_ticker_route_and_keeps_btc_ack_gated():
    matrix = {
        "rows": [
            {
                "ticker": "BTC-USDC",
                "required_timeframes_missing": ["1H", "4H"],
                "baseline_backtest_possible": True,
            },
            {
                "ticker": "ETH-USDC",
                "required_timeframes_missing": ["1H", "4H", "1D"],
                "baseline_backtest_possible": False,
            },
        ],
        "summary": {"blocked_tickers": ["BTC-USDC", "ETH-USDC"]},
    }
    scaffold = {"summary": {"all_parameter_reviews_blocked": True}}
    equivalence = {"summary": {"non_equivalent_tickers": ["BTC-USDC", "ETH-USDC"]}}

    report = build_24h_live_test_readiness_v3(
        readiness_matrix=matrix,
        backlearning_scaffold=scaffold,
        workflow_equivalence=equivalence,
    )

    assert report["routes"]["btc_usdc_only_24h"]["status"] == "warn_ack_required"
    assert report["routes"]["all_ticker_24h"]["status"] == "blocked"
    assert report["routes"]["all_ticker_24h"]["learning_to_execution_enabled"] is False
    assert report["backlearning_status"]["parameter_review_approved"] is False
    assert report["backlearning_status"]["optimization_performed"] is False
    assert report["contains_live_instructions"] is False
