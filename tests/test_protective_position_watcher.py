from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.protective_position_watcher import build_protective_position_watcher_report


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "position_id": "pos-1",
        "entry_price": "100",
        "position_size_base": "1",
        "bot_managed_base": "1",
        "position_size_quote": "100",
        "stop_price": "97",
        "invalidation_price": "97",
        "trailing_trigger_pct": "0.02",
        "trailing_distance_pct": "0.03",
    }
    payload.update(overrides)
    return payload


def _d3_exit(**overrides):
    payload = {
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "size_base": "1",
        "remaining_size": "1",
        "limit_price": "105",
        "exchange_order_id": "cb-tp-1",
    }
    payload.update(overrides)
    return payload


def _pending_buy(**overrides):
    payload = {
        "client_order_id": "phasec-BTCUSDC-buy",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "execution_action": "place_limit_buy",
        "limit_price": "99",
    }
    payload.update(overrides)
    return payload


def test_pending_buy_only_never_generates_stop_sell_action():
    report = build_protective_position_watcher_report(
        positions={},
        open_orders={"orders": {"buy": _pending_buy()}},
        market_by_ticker={"BTC-USDC": {"mid_price": "96"}},
    )
    assert report["position_count"] == 0
    assert report["pending_buy_entries"][0]["stop_sell_action_allowed"] is False
    assert report["pending_buy_entries"][0]["recommended_action"] == "use_pending_entry_cancel_lifecycle"
    assert report["live_action_attempted"] is False
    assert report["state_write_attempted"] is False


def test_open_position_stop_not_breached_keeps_open_with_d3_exit():
    report = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position()},
        open_orders={"orders": {"tp": _d3_exit()}},
        market_by_ticker={"BTC-USDC": {"mid_price": "100"}},
    )
    row = report["positions"][0]
    assert row["stop_breached"] is False
    assert row["recommended_action"] == "keep_open"
    assert row["open_d3_exit_orders"] == 1


def test_stop_breached_with_open_tp_recommends_cancel_tp_then_stop_preview():
    report = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position()},
        open_orders={"orders": {"tp": _d3_exit()}},
        market_by_ticker={"BTC-USDC": {"mid_price": "96"}},
    )
    row = report["positions"][0]
    assert row["stop_breached"] is True
    assert row["reserved_base"] == "1"
    assert row["recommended_action"] == "cancel_tp_then_stop_exit_preview"
    assert row["live_action_attempted"] is False


def test_stop_breached_without_tp_recommends_stop_sell_preview():
    report = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position()},
        open_orders={"orders": {}},
        market_by_ticker={"BTC-USDC": {"mid_price": "96"}},
    )
    assert report["positions"][0]["recommended_action"] == "controlled_stop_sell_preview"


def test_d3_missing_after_fill_recommends_create_preview():
    report = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position()},
        open_orders={"orders": {}},
        market_by_ticker={"BTC-USDC": {"mid_price": "100"}},
    )
    assert report["positions"][0]["recommended_action"] == "d3_missing_create_preview"


def test_risk_state_incomplete_blocks_new_same_ticker_entries():
    report = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position(stop_price="0", invalidation_price="0", protective_stop_status="position_risk_incomplete")},
        open_orders={"orders": {}},
        market_by_ticker={"BTC-USDC": {"mid_price": "100"}},
    )
    row = report["positions"][0]
    assert row["recommended_action"] == "risk_state_incomplete"
    assert "BTC-USDC" in report["blocked_new_entry_tickers"]
    assert "stop_price_missing" in row["blockers"]


def test_watcher_does_not_call_coinbase_unless_read_only_enabled():
    class Client:
        pass

    no_read = build_protective_position_watcher_report(positions={"BTC-USDC": _position()}, open_orders={}, coinbase_client=Client())
    read = build_protective_position_watcher_report(
        positions={"BTC-USDC": _position()},
        open_orders={},
        allow_coinbase_read_only=True,
        coinbase_client=Client(),
    )
    assert no_read["coinbase_call_attempted"] is False
    assert read["coinbase_call_attempted"] is True
    assert read["live_action_attempted"] is False


def test_show_tool_reads_fixtures_without_mutating_state(tmp_path: Path):
    positions = tmp_path / "positions.json"
    orders = tmp_path / "open_orders.json"
    market = tmp_path / "market.json"
    positions.write_text(json.dumps({"BTC-USDC": _position()}), encoding="utf-8")
    orders.write_text(json.dumps({"orders": {"tp": _d3_exit()}}), encoding="utf-8")
    market.write_text(json.dumps({"BTC-USDC": {"mid_price": "96"}}), encoding="utf-8")
    before_positions = positions.read_text(encoding="utf-8")
    before_orders = orders.read_text(encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_protective_position_watcher_status.py",
            "--positions-file",
            str(positions),
            "--open-orders-file",
            str(orders),
            "--market-file",
            str(market),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)
    assert report["positions"][0]["recommended_action"] == "cancel_tp_then_stop_exit_preview"
    assert positions.read_text(encoding="utf-8") == before_positions
    assert orders.read_text(encoding="utf-8") == before_orders
