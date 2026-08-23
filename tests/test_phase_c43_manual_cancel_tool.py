from __future__ import annotations

from bot.order_store import OrderStore
from tools.mark_phase_c43_live_order_cancelled import build_cancel_updates


def test_manual_cancel_updates_make_order_final_and_non_position(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-smoke-20260518072548",
        "exchange_order_id": "fb442875-8c08-47c6-89ff-e674382e24d4",
        "order_id": "fb442875-8c08-47c6-89ff-e674382e24d4",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "status": "submitted",
        "remaining_size": "0.00013333",
        "remaining_quote": "10.00",
        "size_base": "0.00013333",
        "size_quote": "10.00",
    }, event_type="seed")

    updates = build_cancel_updates(reason="manual_cancel_on_coinbase", now="2026-05-18T08:09:02+00:00")
    updated = store.update_order(
        "phasec-BTCUSDC-smoke-20260518072548",
        updates,
        event_type="phase_c43_live_entry_order_manually_cancelled",
    )

    assert updated["status"] == "cancelled"
    assert updated["remaining_size"] == "0"
    assert updated["remaining_quote"] == "0"
    assert updated["position_created"] is False
    assert updated["d2_plan_created"] is False
    assert updated["live_exit_order_created"] is False
    assert store.open_entry_orders("BTC-USDC") == []
