from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.order_lifecycle import is_open_order_status
from bot.order_store import OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import scan_open_d3_exit_lifecycle_orders
from bot.state_store import StateStore


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _d3_order(*, client_order_id: str, status: str) -> dict:
    return {
        "client_order_id": client_order_id,
        "exchange_order_id": f"exchange-{client_order_id}",
        "order_id": f"exchange-{client_order_id}",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": status,
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "size_base": "0.001",
        "remaining_size": "0.001",
        "limit_price": "100.00",
    }


@pytest.mark.parametrize("status", ["open", "active", "new", "queued", "unknown", ""])
def test_nonfinal_exchange_statuses_remain_open_and_reserved(tmp_path: Path, status: str) -> None:
    store = _orders(tmp_path)
    client_order_id = f"phased3-BTCUSDC-TP1-{status or 'blank'}"
    store.upsert_order(_d3_order(client_order_id=client_order_id, status=status))

    persisted = store.get_order(client_order_id)
    assert persisted is not None
    assert is_open_order_status(persisted["status"]) is True
    assert [row["client_order_id"] for row in store.open_exit_orders("BTC-USDC")] == [client_order_id]
    assert [row["client_order_id"] for row in scan_open_d3_exit_lifecycle_orders(store)] == [client_order_id]


def test_terminal_alias_is_normalized_and_releases_reservation(tmp_path: Path) -> None:
    store = _orders(tmp_path)
    client_order_id = "phased3-BTCUSDC-TP1-terminal"
    store.upsert_order(_d3_order(client_order_id=client_order_id, status="COMPLETED"))

    persisted = store.get_order(client_order_id)
    assert persisted is not None
    assert persisted["status"] == "filled"
    assert store.open_exit_orders("BTC-USDC") == []
    assert [row["client_order_id"] for row in store.final_orders("BTC-USDC")] == [client_order_id]


def test_position_reads_do_not_persist_normalization(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    positions_path = state_dir / "positions.json"
    raw = {"btc-usdc": {"ticker": "btc-usdc", "status": "open", "position_size_base": "1"}}
    positions_path.write_text(json.dumps(raw), encoding="utf-8")
    before = positions_path.read_bytes()

    positions = StateStore().get_positions()

    assert "BTC-USDC" in positions
    assert positions_path.read_bytes() == before


def test_daily_pnl_read_does_not_roll_the_file_forward(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    daily_path = state_dir / "daily_pnl.json"
    daily_path.write_text('{"date":"2000-01-01","realized_pnl":1.0}', encoding="utf-8")
    before = daily_path.read_bytes()

    report = StateStore().get_daily_pnl()

    assert report["date"] != "2000-01-01"
    assert report["realized_pnl"] == 0.0
    assert daily_path.read_bytes() == before
