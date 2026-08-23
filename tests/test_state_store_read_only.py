from __future__ import annotations

from pathlib import Path

from bot import state_store as state_store_module
from bot.order_store import OrderStore
from bot.state_store import StateStore


def test_order_store_construction_and_reads_do_not_create_files(tmp_path: Path) -> None:
    store_root = tmp_path / "runtime-state"
    store = OrderStore(
        path=store_root / "open_orders.json",
        log_path=store_root / "order_events.jsonl",
    )

    assert store.all_orders() == []
    assert store.get_order("missing") is None
    assert store.open_orders() == []
    assert not store_root.exists()


def test_state_store_construction_and_reads_do_not_create_files(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "runtime-state"
    monkeypatch.setattr(state_store_module, "STATE_DIR", state_root)

    store = StateStore()

    assert store.get_positions() == {}
    assert store.get_daily_pnl()["realized_pnl"] == 0.0
    assert store.cooldown_active("BTC-USDC") is False
    assert not state_root.exists()


def test_explicit_order_store_mutation_creates_its_files(tmp_path: Path) -> None:
    store_root = tmp_path / "runtime-state"
    store = OrderStore(
        path=store_root / "open_orders.json",
        log_path=store_root / "order_events.jsonl",
    )

    stored = store.upsert_order({
        "client_order_id": "paper-BTCUSDC-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
    })

    assert stored["client_order_id"] == "paper-BTCUSDC-1"
    assert (store_root / "open_orders.json").exists()
    assert (store_root / "order_events.jsonl").exists()
