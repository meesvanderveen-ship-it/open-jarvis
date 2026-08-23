from __future__ import annotations

from datetime import datetime, timezone

from bot.pending_entry_lifecycle import evaluate_pending_entry_lifecycle
from bot.phase_d4_trailing_preview import build_phase_d4_trailing_preview_report
from bot.protective_position_watcher import build_protective_position_watcher_report


def _pending_buy(**overrides):
    payload = {
        "client_order_id": "phasec-ETHUSDC-buy",
        "exchange_order_id": "cb-buy-1",
        "ticker": "ETH-USDC",
        "product_id": "ETH-USDC",
        "side": "BUY",
        "status": "submitted",
        "execution_action": "place_limit_buy",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "limit_price": "100",
        "invalidation_level": "98",
        "trade_plan_snapshot": {
            "plan_action": "prepare_buy",
            "entry_zone_low": "99.5",
            "entry_zone_high": "100.2",
            "invalidation_price": "98",
            "take_profit_1": "104",
        },
    }
    payload.update(overrides)
    return payload


def test_pending_buy_invalidation_breach_is_cancel_preview_not_stop_sell():
    lifecycle = evaluate_pending_entry_lifecycle(
        order=_pending_buy(),
        current_market={"mid_price": "97.5", "best_bid": "97.49", "best_ask": "97.51", "spread_pct": "0.0002"},
    )
    watcher = build_protective_position_watcher_report(
        positions={},
        open_orders={"orders": {"buy": _pending_buy()}},
        market_by_ticker={"ETH-USDC": {"mid_price": "97.5"}},
    )
    assert lifecycle["lifecycle_action"] == "cancel_preview"
    assert watcher["position_count"] == 0
    assert watcher["pending_buy_entries"][0]["stop_sell_action_allowed"] is False


def test_pending_buy_with_no_position_has_no_naked_sell_path():
    report = build_protective_position_watcher_report(
        positions={},
        open_orders={"orders": {"buy": _pending_buy()}},
        market_by_ticker={"ETH-USDC": {"mid_price": "90"}},
    )
    assert report["pending_buy_entries"][0]["reason"] == "pending_buy_has_no_base_position_no_naked_sell"
    assert report["live_action_attempted"] is False


def test_d4_ignores_pending_buy_entries_because_it_requires_open_d3_sell():
    pending = _pending_buy()
    report = build_phase_d4_trailing_preview_report(
        ticker="ETH-USDC",
        linked_position_id="pos-1",
        current_order=None,
        position={"ticker": "ETH-USDC", "status": "open", "position_size_base": "1", "reserved_base_open_exit_orders": "1"},
        market_snapshot={"best_bid": "99", "best_ask": "100", "mid_price": "99.5", "timestamp": datetime.now(timezone.utc).isoformat()},
        product_rules={"base_increment": "0.00000001", "price_increment": "0.01", "min_order_quote": "1"},
        policy={"activation_price": "101", "trailing_distance_pct": "0.02"},
        open_orders=[pending],
        now=datetime.now(timezone.utc),
    )
    assert report["status"] == "d4_trailing_preview_blocked"
    assert "open_d3_exit_order_not_found" in report["blockers"]
    assert report["no_live_action"] is True
