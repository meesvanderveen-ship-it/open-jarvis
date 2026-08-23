from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d1_exit_orderbook_scaffold import (
    assess_phase_d1_exit_readiness,
    build_phase_d1_exit_order_intent_from_position,
    build_phase_d1_exit_payload_preview,
    build_phase_d1_status_report,
    count_local_phase_d1_live_exit_orders,
    reconcile_phase_d1_exit_fills_to_positions,
)


def cfg(**overrides):
    base = dict(
        enable_phase_d1_exit_orderbook_scaffold=True,
        enable_phase_d1_actual_exit_submit=False,
        phase_d1_max_exit_order_quote="25.00",
        phase_d1_max_open_exit_orders=4,
        phase_d1_require_reduce_only=True,
        phase_d1_exit_order_post_only=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        phase_c_allowed_tickers=["BTC-USDC", "SUI-USDC"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class DummyStateStore:
    def __init__(self):
        self.positions = {
            "BTC-USDC": {
                "ticker": "BTC-USDC",
                "status": "open",
                "position_size_base": "0.001",
                "bot_managed_base": "0.001",
                "entry_price": "50000",
                "order_id": "entry-1",
            }
        }

    def get_positions(self):
        return self.positions

    def get_position(self, ticker):
        return self.positions.get(ticker)

    def force_sync_position_base(self, ticker, actual_base_size, current_price=None):
        self.positions[ticker]["position_size_base"] = str(actual_base_size)
        self.positions[ticker]["bot_managed_base"] = str(actual_base_size)
        if current_price is not None:
            self.positions[ticker]["last_exit_price"] = str(current_price)
        return self.positions[ticker]

    def mark_position_closed(self, ticker, close_reason="", close_price="0", realized_pnl=None):
        self.positions[ticker]["status"] = "closed"
        self.positions[ticker]["position_size_base"] = "0"
        self.positions[ticker]["bot_managed_base"] = "0"
        self.positions[ticker]["close_reason"] = close_reason
        self.positions[ticker]["close_price"] = str(close_price)
        return self.positions[ticker]


def test_d1_builds_reduce_only_exit_preview_within_caps(tmp_path: Path):
    c = cfg()
    position = {
        "ticker": "BTC-USDC",
        "status": "open",
        "position_size_base": "0.001",
        "bot_managed_base": "0.001",
        "entry_price": "50000",
    }
    intent = build_phase_d1_exit_order_intent_from_position(
        cfg=c,
        position=position,
        action="reduce_size",
        reduce_fraction="0.50",
        limit_price="50000",
    )
    assert intent["side"] == "SELL"
    assert intent["execution_action"] == "place_limit_sell"
    assert intent["reduce_only_local"] is True
    assert float(intent["estimated_quote_value"]) <= 25.0

    readiness = assess_phase_d1_exit_readiness(
        cfg=c,
        position=position,
        exit_intent=intent,
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        open_live_exit_orders_count=0,
    )
    assert readiness["ready_no_submit"] is True
    assert readiness["status"] == "d1_exit_scaffold_ready_no_submit"

    payload = build_phase_d1_exit_payload_preview(cfg=c, exit_intent=intent, readiness=readiness)
    assert payload["accepted"] is True
    assert payload["side"] == "SELL"
    assert payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]["post_only"] is True


def test_d1_blocks_sell_larger_than_position(tmp_path: Path):
    c = cfg()
    position = {"ticker": "BTC-USDC", "status": "open", "position_size_base": "0.001", "bot_managed_base": "0.001", "entry_price": "50000"}
    intent = {
        "ticker": "BTC-USDC",
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "size_base": "0.002",
        "limit_price": "50000",
        "estimated_quote_value": "100",
        "reduce_only_local": True,
    }
    readiness = assess_phase_d1_exit_readiness(
        cfg=c,
        position=position,
        exit_intent=intent,
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        open_live_exit_orders_count=0,
    )
    assert readiness["ready_no_submit"] is False
    assert "sell_base_exceeds_position_base" in readiness["blockers"]
    assert "estimated_quote_missing_or_above_d1_cap" in readiness["blockers"]


def test_d1_counts_local_exit_orders(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased1-BTCUSDC-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "mode": "phase_d1_exit",
        "execution_action": "place_limit_sell",
    })
    counts = count_local_phase_d1_live_exit_orders(store)
    assert counts["total_open_live_exit_orders"] == 1
    assert counts["tickers"] == ["BTC-USDC"]


def test_d1_exit_fill_reduces_position(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased1-BTCUSDC-2",
        "exchange_order_id": "ex-2",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "mode": "phase_d1_exit",
        "execution_action": "place_limit_sell",
        "size_base": "0.0004",
        "limit_price": "50000",
    })
    state = DummyStateStore()
    result = reconcile_phase_d1_exit_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phased1-BTCUSDC-2",
            "order_id": "ex-2",
            "product_id": "BTC-USDC",
            "side": "SELL",
            "status": "filled",
            "filled_size": "0.0004",
            "average_filled_price": "50000",
        }],
    )
    assert result["status"] == "exit_fill_reconciliation_completed"
    assert result["actions"][0]["action"] == "exit_fill_to_position_update"
    assert state.positions["BTC-USDC"]["status"] == "open"
    assert state.positions["BTC-USDC"]["position_size_base"] == "0.0006"


def test_d1_exit_fill_closes_position(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased1-BTCUSDC-3",
        "exchange_order_id": "ex-3",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "mode": "phase_d1_exit",
        "execution_action": "place_limit_sell",
        "size_base": "0.001",
        "limit_price": "50000",
    })
    state = DummyStateStore()
    result = reconcile_phase_d1_exit_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phased1-BTCUSDC-3",
            "order_id": "ex-3",
            "product_id": "BTC-USDC",
            "side": "SELL",
            "status": "filled",
            "filled_size": "0.001",
            "average_filled_price": "50000",
        }],
    )
    assert result["actions"][0]["action"] == "exit_fill_to_position_update"
    assert state.positions["BTC-USDC"]["status"] == "closed"
    assert state.positions["BTC-USDC"]["close_reason"] == "phase_d1_live_limit_sell_filled"


def test_d1_status_report_is_safe_without_position(tmp_path: Path):
    report = build_phase_d1_status_report(
        cfg=cfg(),
        ticker="SUI-USDC",
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        state_store=DummyStateStore(),
    )
    assert report["selected_position_present"] is False
    assert report["fill_reconciliation_preview"]["status"] == "exit_fill_reconciliation_completed"
    assert report["safety_policy"]["no_live_exit_submit_in_d1"] is True
