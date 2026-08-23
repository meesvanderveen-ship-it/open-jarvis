from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_local_position_recovery import (
    PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
    RECOVERY_REASON,
    RECOVERY_SOURCE,
    RECOVERY_VALUES_SOURCE,
    build_phase_d3_local_position_recovery_report,
)
from bot.state_store import StateStore


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


def _seed_position(state: StateStore) -> None:
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "closed",
            "order_id": "pos-1",
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_size_base": "0",
            "position_size_quote": "0",
            "bot_managed_base": "0",
            "close_reason": "inventory_sync_live_notional_below_min_trade_quote",
            "synthetic_close_reason": "inventory_sync_live_notional_below_min_trade_quote",
            "synthetic_closed_at": "2026-05-26T16:00:00.517331+00:00",
            "close_time": "2026-05-26T16:00:00.517331+00:00",
            "last_heartbeat_status": "closed_tiny_residual",
            "last_heartbeat_reason": "inventory_sync_live_notional_below_min_trade_quote",
            "monitoring_enabled": False,
            "partial_take_profit_taken": True,
            "recovered_from_closed_tiny_residual": True,
            "recovery_reason": "live_base_present_after_inventory_sync_tiny_residual_close",
        },
    )


def _seed_live_exit(
    orders: OrderStore,
    *,
    client_order_id: str = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
    exchange_order_id: str = "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
    linked_position_id: str = "76310097-849e-481c-b587-ba44bc3330fe",
    status: str = "submitted",
    remaining_size: str = "0.00006489",
    filled_base: str = "0",
    fill_count: int = 0,
) -> None:
    orders.upsert_order(
        {
            "client_order_id": client_order_id,
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": status,
            "phase": "D3_controlled_live_reduce_only_exits",
            "linked_position_id": linked_position_id,
            "exchange_order_id": exchange_order_id,
            "order_id": exchange_order_id,
            "execution_action": "place_limit_sell",
            "d3_exit_label": "TP1",
            "size_base": "0.00006489",
            "remaining_size": remaining_size,
            "filled_base": filled_base,
            "fill_count": fill_count,
            "limit_price": "81664.97",
        }
    )


def _report(
    tmp_path: Path,
    monkeypatch,
    *,
    apply: bool = False,
    recovery_ack: str = "",
    position_size_base: str = "0.0000649067431275",
    reserved_base_open_exit_orders: str = "0.00006489",
    bot_managed_base: str = "0.0001297967431275",
):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_live_exit(orders)
    return build_phase_d3_local_position_recovery_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        position_size_base=position_size_base,
        reserved_base_open_exit_orders=reserved_base_open_exit_orders,
        bot_managed_base=bot_managed_base,
        apply=apply,
        recovery_ack=recovery_ack,
        order_store=orders,
        state_store=state,
    )


def test_preview_proposes_reconstruction_without_writing(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_live_exit(orders)
    before = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")

    report = build_phase_d3_local_position_recovery_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        position_size_base="0.0000649067431275",
        reserved_base_open_exit_orders="0.00006489",
        bot_managed_base="0.0001297967431275",
        order_store=orders,
        state_store=state,
    )
    after = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")

    assert report["status"] == "d3_local_position_recovery_preview_ready"
    assert report["suggested_action"] == "preview_only"
    assert report["no_state_write"] is True
    assert report["state_write_performed"] is False
    assert report["blockers"] == []
    assert report["proposed_position_updates"]["status"] == "open"
    assert report["proposed_position_updates"]["position_size_base"] == "0.0000649067431275"
    assert report["proposed_position_updates"]["reserved_base_open_exit_orders"] == "0.00006489"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.0001297967431275"
    assert report["proposed_position_updates"]["recovery_reason"] == RECOVERY_REASON
    assert report["proposed_position_updates"]["recovery_source"] == RECOVERY_SOURCE
    assert report["proposed_position_updates"]["recovery_linked_d3_client_order_id"] == "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    assert report["proposed_position_updates"]["recovery_linked_d3_exchange_order_id"] == "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"
    assert report["proposed_position_updates"]["recovery_linked_position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"
    assert report["proposed_position_updates"]["recovery_preview_values_source"] == RECOVERY_VALUES_SOURCE
    assert report["proposed_position_updates"]["recovery_preview_only"] is True
    assert before == after


def test_apply_requires_ack(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, apply=True)
    state = StateStore()
    position = state.get_position("BTC-USDC")

    assert report["status"] == "d3_local_position_recovery_blocked"
    assert report["suggested_action"] == "ack_required"
    assert "recovery_apply_ack_required" in report["blockers"]
    assert report["state_write_performed"] is False
    assert report["no_state_write"] is True
    assert position["status"] == "closed"
    assert position["position_size_base"] == "0"
    assert position["bot_managed_base"] == "0"


def test_apply_in_tmp_path_with_ack_restores_local_position(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        apply=True,
        recovery_ack=PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
    )
    state = StateStore()
    orders = _orders(tmp_path)
    position = state.get_position("BTC-USDC")
    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert report["status"] == "d3_local_position_recovery_applied"
    assert report["suggested_action"] == "applied"
    assert report["state_write_performed"] is True
    assert report["no_state_write"] is False
    assert position["status"] == "open"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["bot_managed_base"] == "0.0001297967431275"
    assert position["reserved_base_open_exit_orders"] == "0.00006489"
    assert position["recovery_reason"] == RECOVERY_REASON
    assert position["recovery_source"] == RECOVERY_SOURCE
    assert position["recovery_linked_position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"
    assert position["monitoring_enabled"] is True
    assert position["previous_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert position["close_reason"] == ""
    assert position["synthetic_close_reason"] == ""
    assert order["status"] == "submitted"
    assert order["remaining_size"] == "0.00006489"
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["coinbase_call_attempted"] is False


def test_blocks_if_d3_order_missing_or_mismatched(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_live_exit(orders, client_order_id="other", exchange_order_id="other", linked_position_id="other-pos")

    report = build_phase_d3_local_position_recovery_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        position_size_base="0.0000649067431275",
        reserved_base_open_exit_orders="0.00006489",
        bot_managed_base="0.0001297967431275",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "d3_local_position_recovery_blocked"
    assert "recovery_client_order_id_mismatch" in report["blockers"] or "recovery_open_d3_order_missing" in report["blockers"]
    assert report["state_write_performed"] is False


def test_blocks_if_filled_evidence_exists(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_live_exit(orders, filled_base="0.00001", fill_count=1)

    report = build_phase_d3_local_position_recovery_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        position_size_base="0.0000649067431275",
        reserved_base_open_exit_orders="0.00006489",
        bot_managed_base="0.0001297967431275",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "d3_local_position_recovery_blocked"
    assert "recovery_filled_evidence_present" in report["blockers"]


def test_blocks_if_math_inconsistent(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        position_size_base="0.0000649067431275",
        reserved_base_open_exit_orders="0.00006489",
        bot_managed_base="0.00012000",
    )

    assert report["status"] == "d3_local_position_recovery_blocked"
    assert "recovery_proposed_base_math_incoherent" in report["blockers"]


def test_blocks_when_replication_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("REPLICATION_ENABLED", "true")
    report = _report(tmp_path, monkeypatch)

    assert report["status"] == "d3_local_position_recovery_blocked"
    assert "recovery_replication_enabled_forbidden" in report["blockers"]
    assert report["no_state_write"] is True
