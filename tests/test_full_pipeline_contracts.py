from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d1_fill_position import (
    reconcile_entry_fill_to_position,
    validate_entry_fill_to_position_contract,
)
from bot.state_store import StateStore


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state/open_orders.json",
        log_path=tmp_path / "logs/order_events.jsonl",
    )


def _seed_entry_order(store: OrderStore) -> None:
    store.upsert_order(
        {
            "client_order_id": "phasec-BTCUSDC-fill-contract",
            "exchange_order_id": "cb-entry-fill-1",
            "order_id": "cb-entry-fill-1",
            "ticker": "BTC-USDC",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "submitted",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "phase": "C4.3_autonomous_entry_live_activation_fill_to_position_bridge",
            "size_base": "0.25",
            "remaining_size": "0.25",
            "size_quote": "25.00",
            "remaining_quote": "25.00",
            "limit_price": "100.00",
            "execution_action": "place_limit_buy",
            "stop_price": "98.00",
            "invalidation_price": "98.00",
        }
    )


def _filled_snapshot():
    return {
        "client_order_id": "phasec-BTCUSDC-fill-contract",
        "order_id": "cb-entry-fill-1",
        "exchange_order_id": "cb-entry-fill-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "filled_size": "0.25",
        "average_filled_price": "100.00",
        "filled_value": "25.00",
    }


def test_fill_evidence_contract_requires_terminal_fill_before_position_registration() -> None:
    blocked = validate_entry_fill_to_position_contract(
        local_order={"exchange_order_id": "cb-entry-fill-1"},
        live_order_snapshot={"status": "OPEN", "filled_size": "0", "order_id": "cb-entry-fill-1"},
    )
    accepted = validate_entry_fill_to_position_contract(
        local_order={"exchange_order_id": "cb-entry-fill-1"},
        live_order_snapshot=_filled_snapshot(),
    )

    assert blocked["accepted"] is False
    assert "terminal_fill_status_required" in blocked["blockers"]
    assert accepted["accepted"] is True
    assert accepted["state_write_allowed"] is True


def test_fill_to_position_happy_path_creates_position_and_clears_reserved_quote(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    store = _orders(tmp_path)
    _seed_entry_order(store)

    preview = reconcile_entry_fill_to_position(
        cfg=SimpleNamespace(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_filled_snapshot()],
        apply_local=False,
    )
    assert preview["actions"][0]["action"] == "filled_to_position"
    assert state.get_position("BTC-USDC") is None

    applied = reconcile_entry_fill_to_position(
        cfg=SimpleNamespace(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_filled_snapshot()],
        apply_local=True,
    )
    position = state.get_position("BTC-USDC")
    order = store.get_order("phasec-BTCUSDC-fill-contract")

    assert applied["actions"][0]["action"] == "filled_to_position"
    assert position is not None
    assert position["position_size_base"] == "0.25"
    assert position["entry_price"] == "100.00"
    assert position["stop_price"] == "98.00"
    assert position["invalidation_price"] == "98.00"
    assert position["protective_stop_status"] == "protective_stop_state_complete"
    assert position["position_risk_incomplete"] is False
    assert order["status"] == "filled"
    assert order["remaining_quote"] == "0"
    assert order["position_created"] is True
