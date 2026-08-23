from __future__ import annotations

from types import SimpleNamespace

from bot.phase_c45_maker_price_scout import build_phase_c45_maker_price_scout_report


def cfg(**overrides):
    base = dict(
        replication_enabled=False,
        enable_phase_c_actual_coinbase_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeCoinbaseClient:
    def __init__(self, *, bid="103000.00", ask="103001.00"):
        self.bid = bid
        self.ask = ask

    def get_product(self, product_id):
        return {
            "product_id": product_id,
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "quote_min_size": "1.00",
        }

    def get_product_book(self, product_id, limit=5):
        return {
            "product_id": product_id,
            "bids": [{"price": self.bid, "size": "0.5"}],
            "asks": [{"price": self.ask, "size": "0.4"}],
            "time": "2026-05-18T18:00:00Z",
            "source_path": "/fake/book",
            "depth_is_top_only": False,
        }


def test_maker_price_scout_joins_best_bid_with_numeric_command():
    report = build_phase_c45_maker_price_scout_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        coinbase_client=FakeCoinbaseClient(),
        quote_size="10.00",
    )

    assert report["status"] == "maker_price_ready"
    assert report["maker_price"]["limit_price"] == "103000.00"
    assert "<" not in report["commands"]["submit_live"]
    assert "103000.00" in report["commands"]["submit_live"]
    assert report["safety_policy"]["does_not_place_entry_orders"] is True


def test_maker_price_scout_can_place_one_tick_below_bid():
    report = build_phase_c45_maker_price_scout_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        coinbase_client=FakeCoinbaseClient(bid="103000.00", ask="103002.00"),
        quote_size="10.00",
        bid_ticks_below=1,
    )

    assert report["status"] == "maker_price_ready"
    assert report["maker_price"]["limit_price"] == "102999.99"
    assert report["maker_price"]["distance_from_best_bid_abs"] == "0.01"


def test_maker_price_scout_blocks_when_actual_submit_still_enabled():
    report = build_phase_c45_maker_price_scout_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        coinbase_client=FakeCoinbaseClient(),
        quote_size="10.00",
    )

    assert report["status"] == "blocked_review_required"
    assert "entry_actual_submit_still_enabled" in report["blockers"]


def test_maker_price_scout_blocks_crossed_or_missing_book():
    report = build_phase_c45_maker_price_scout_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        coinbase_client=FakeCoinbaseClient(bid="103001.00", ask="103001.00"),
        quote_size="10.00",
    )

    assert report["status"] == "blocked_review_required"
    assert "bid_ask_spread_invalid_or_crossed" in report["blockers"]
