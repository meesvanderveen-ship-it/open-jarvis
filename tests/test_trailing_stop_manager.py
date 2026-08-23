from __future__ import annotations

from bot.trailing_stop_manager import build_trailing_stop_status


def test_trailing_stop_ratchets_up_and_never_down():
    report = build_trailing_stop_status(
        position={"entry_price": "100", "highest_price_since_entry": "120", "trailing_stop_price": "115"},
        market={"mid_price": "110"},
        policy={"activation_profit_pct": "0.02", "trailing_distance_pct": "0.10"},
    )
    assert report["status"] == "triggered_preview"
    assert report["trailing_stop_price"] == "115"
    assert report["stop_moved_down"] is False
    assert report["live_action_attempted"] is False


def test_trailing_stop_updates_peak_preview_only():
    report = build_trailing_stop_status(
        position={"entry_price": "100", "highest_price_since_entry": "120", "trailing_stop_price": "108"},
        market={"mid_price": "130"},
        policy={"activation_profit_pct": "0.02", "trailing_distance_pct": "0.10"},
    )
    assert report["status"] == "active"
    assert report["highest_price_since_entry"] == "130"
    assert report["trailing_stop_price"] == "117.00"
    assert report["state_write_performed"] is False
