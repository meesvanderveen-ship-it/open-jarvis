from __future__ import annotations

from datetime import datetime, timezone

from bot.orderbook_analyzer import build_orderbook_summary


def test_build_orderbook_summary_from_feature_pack_and_raw_levels():
    feature_pack = {
        "ticker": "ADA-USDC",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": {
            "best_bid": "0.2800",
            "best_ask": "0.2804",
            "mid_price": "0.2802",
        },
        "indicators": {
            "1h": {
                "donchian_20_low": "0.2700",
                "donchian_20_high": "0.2900",
                "bb_lower": "0.2720",
                "bb_upper": "0.2880",
            }
        },
        "microstructure": {
            "15m": {"volume_vs_avg": 1.2},
            "1h": {"volume_vs_avg": 1.1},
        },
        "structure": {"range_position": 0.51},
        "orderbook_context": {"snapshot_available": True},
    }
    raw_orderbook = {
        "product_id": "ADA-USDC",
        "bids": [
            {"price": "0.2800", "size": "100"},
            {"price": "0.2798", "size": "300"},
            {"price": "0.2796", "size": "90"},
        ],
        "asks": [
            {"price": "0.2804", "size": "80"},
            {"price": "0.2808", "size": "250"},
        ],
    }

    summary = build_orderbook_summary(feature_pack, raw_orderbook=raw_orderbook)

    assert summary["ticker"] == "ADA-USDC"
    assert summary["snapshot_available"] is True
    assert summary["freshness_status"] == "fresh"
    assert summary["top_of_book"]["best_bid"] == "0.2800"
    assert summary["top_of_book"]["best_ask"] == "0.2804"
    assert summary["depth"]["bid_depth_top5_base"] == "490"
    assert summary["clusters"]["bid_clusters"]
    assert summary["passive_buy_zones"]
    assert summary["policy_note"].startswith("Orderbook data is execution context")


def test_build_orderbook_summary_degrades_safely_without_book():
    summary = build_orderbook_summary({"ticker": "BTC-USDC", "market": {}})

    assert summary["ticker"] == "BTC-USDC"
    assert summary["snapshot_available"] is False
    assert summary["top_of_book"]["best_bid"] == "0"
    assert summary["slippage_estimate"]["quality"] == "unknown"
