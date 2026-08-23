from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_cancel_closeout_local_reconcile import (
    D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
    build_phase_d3_cancel_closeout_local_reconcile_report,
)
from bot.state_store import StateStore


EVIDENCE_HASH = "fa283d56ad9221ea03124e9bd5a229f281c2e4981dae09e23f1112f5515d7aac"


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _seed(state: StateStore, orders: OrderStore, *, order_status: str = "submitted") -> None:
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "open",
            "order_id": "pos-1",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_size_base": "0.0000649067431275",
            "bot_managed_base": "0.0001297967431275",
            "reserved_base_open_exit_orders": "0.00006489",
        },
    )
    orders.upsert_order(
        {
            "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": order_status,
            "phase": "D3_controlled_live_reduce_only_exits",
            "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "exchange_order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
            "order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
            "execution_action": "place_limit_sell",
            "d3_exit_label": "TP1",
            "size_base": "0.00006489",
            "remaining_size": "0.00006489",
            "remaining_quote": "5.2992399033",
            "filled_base": "0",
            "filled_quote": "0",
            "fill_count": 0,
            "limit_price": "81664.97",
        }
    )


def _report(tmp_path: Path, monkeypatch, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed(state, orders, order_status=kwargs.pop("order_status", "submitted"))
    return build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        evidence_hash=kwargs.pop("evidence_hash", EVIDENCE_HASH),
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def test_preview_cancelled_closeout_is_read_only(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch)

    assert report["status"] == "d3_cancel_closeout_local_reconcile_preview_ready"
    assert report["mode"] == "preview"
    assert report["evidence_status"] == "cancelled"
    assert report["lifecycle_proposed_action"] == "mark_cancelled"
    assert report["state_write_performed"] is False
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["proposed_order_status_after"] == "cancelled"
    assert report["proposed_reserved_base_open_exit_orders_after"] == "0"
    assert report["position_will_remain_open"] is True


def test_apply_with_correct_ack_marks_cancelled_and_releases_reservation(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed(state, orders)

    report = build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        evidence_hash=EVIDENCE_HASH,
        order_store=orders,
        state_store=state,
        apply=True,
        ack=D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
    )

    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000") or {}
    position = state.get_position("BTC-USDC") or {}
    assert report["status"] == "d3_cancel_closeout_local_reconcile_applied"
    assert report["state_write_performed"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["live_action_performed"] is False
    assert order["status"] == "cancelled"
    assert order["remaining_size"] == "0"
    assert report["open_d3_exit_count_after"] == 0
    assert position["status"] == "open"
    assert position["reserved_base_open_exit_orders"] == "0"


def test_wrong_ack_blocks_without_state_write(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, apply=True, ack="WRONG")

    assert report["status"] == "d3_cancel_closeout_local_reconcile_blocked"
    assert "d3_cancel_closeout_local_reconcile_ack_required" in report["blockers"]
    assert report["state_write_performed"] is False


def test_evidence_hash_mismatch_blocks(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, evidence_hash="bad")

    assert report["status"] == "d3_cancel_closeout_local_reconcile_blocked"
    assert "evidence_hash_mismatch" in report["blockers"]


def test_non_open_local_order_blocks(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, order_status="cancelled")

    assert report["status"] == "d3_cancel_closeout_local_reconcile_blocked"
    assert "local_order_not_open_or_submitted" in report["blockers"]
