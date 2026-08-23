from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_pilot import run_phase_d3_cancel_replace_pilot
from bot.phase_d3_cancel_replace_review import D3_CANCEL_REPLACE_PILOT_ACK
from bot.state_store import StateStore


class _Cfg:
    enable_live_exit_orders = True
    autonomous_allow_exits = True
    enable_phase_d3_actual_exit_submit = True
    phase_c_disable_exit_limit_orders = False


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


def _seed_position(
    state: StateStore,
    *,
    status: str = "open",
    position_size_base: str = "0.0000649067431275",
    reserved: str = "0.00006489",
    bot_managed: str = "0.0001297967431275",
    effective_min_trade_base: str = "0.000001",
) -> None:
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": status,
            "order_id": "pos-1",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_size_base": position_size_base,
            "bot_managed_base": bot_managed,
            "reserved_base_open_exit_orders": reserved,
            "effective_min_trade_base": effective_min_trade_base,
            "exchange_quote_min_size": "1",
        },
    )


def _seed_open_exit(
    orders: OrderStore,
    *,
    client_order_id: str = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
    exchange_order_id: str = "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
    linked_position_id: str = "76310097-849e-481c-b587-ba44bc3330fe",
    remaining_size: str = "0.00006489",
    limit_price: str = "81664.97",
    status: str = "submitted",
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
            "size_base": remaining_size,
            "remaining_size": remaining_size,
            "filled_base": "0",
            "filled_quote": "0",
            "fill_count": 0,
            "limit_price": limit_price,
            "created_at": "2026-05-26T09:00:00+00:00",
            "submitted_at": "2026-05-26T09:00:00+00:00",
        }
    )


def _snapshot(status: str, **overrides):
    payload = {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "fees": "0",
        "evidence_source": "snapshot_fixture_or_preloaded",
    }
    payload.update(overrides)
    return payload


class FakeCoinbaseClient:
    def __init__(self, *, cancel_response=None, replace_response=None, cancel_exc=None, replace_exc=None):
        self.cancel_response = cancel_response if cancel_response is not None else {"success": True, "order_ids": ["bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"]}
        self.replace_response = replace_response if replace_response is not None else {"success": True, "order_id": "repl-order-1"}
        self.cancel_exc = cancel_exc
        self.replace_exc = replace_exc
        self.cancelled = []
        self.replaced = []

    def cancel_order(self, order_id: str):
        self.cancelled.append(order_id)
        if self.cancel_exc is not None:
            raise self.cancel_exc
        return self.cancel_response

    def place_limit_order(self, **kwargs):
        self.replaced.append(dict(kwargs))
        if self.replace_exc is not None:
            raise self.replace_exc
        return self.replace_response


class FailingLookupCoinbaseClient(FakeCoinbaseClient):
    def get_order(self, order_id: str):
        raise RuntimeError("simulated get_order failure")

    def list_orders(self, product_id=None, order_status=None, limit=100, cursor=None):
        raise RuntimeError("simulated list_orders failure")

    def get_recent_fills_for_order(self, order_id, limit=100):
        raise AssertionError("fills should not be called after lookup failure")


def _run(tmp_path: Path, monkeypatch, *, snapshot=None, client=None, position_kwargs=None, order_kwargs=None, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, **(position_kwargs or {}))
    _seed_open_exit(orders, **(order_kwargs or {}))
    return run_phase_d3_cancel_replace_pilot(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        cfg=_Cfg(),
        order_store=orders,
        state_store=state,
        snapshot=snapshot,
        coinbase_client=client,
        **kwargs,
    )


def test_preview_without_ack_is_ready(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient()
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=client,
        allow_coinbase_poll=True,
    )

    assert report["status"] == "cancel_replace_pilot_preview_ready"
    assert report["pilot_decision"] == "await_explicit_ack_for_live_cancel_replace_pilot"
    assert report["cancel_attempted"] is False
    assert report["replace_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False
    assert client.cancelled == []
    assert client.replaced == []


def test_wrong_ack_blocks(tmp_path: Path, monkeypatch) -> None:
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack="WRONG",
    )

    assert report["status"] == "cancel_replace_pilot_blocked_ack_required"
    assert report["cancel_attempted"] is False
    assert report["replace_attempted"] is False


def test_missing_allow_live_cancel_blocks_whole_pilot(tmp_path: Path, monkeypatch) -> None:
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        allow_coinbase_poll=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert "pilot_live_flags_missing" in report["blockers"]
    assert report["cancel_attempted"] is False
    assert report["replace_attempted"] is False


def test_missing_allow_live_replace_blocks_whole_pilot(tmp_path: Path, monkeypatch) -> None:
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert "pilot_live_flags_missing" in report["blockers"]
    assert report["cancel_attempted"] is False
    assert report["replace_attempted"] is False


def test_preflight_not_ready_blocks(tmp_path: Path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch)
    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert report["preflight_status"] == "cancel_replace_pilot_preflight_needs_fresh_open_evidence"


def test_poll_failure_diagnostics_are_exposed_without_live_action(tmp_path: Path, monkeypatch) -> None:
    client = FailingLookupCoinbaseClient()
    report = _run(
        tmp_path,
        monkeypatch,
        client=client,
        allow_coinbase_poll=True,
    )

    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert report["preflight_status"] == "cancel_replace_pilot_preflight_coinbase_poll_failed"
    assert report["coinbase_call_attempted"] is True
    assert report["coinbase_call_succeeded"] is False
    assert report["coinbase_error_type"] == "RuntimeError"
    assert "simulated list_orders failure" in report["coinbase_error_message"]
    assert report["coinbase_error_stage"] == "lookup_order"
    assert report["coinbase_lookup_methods_attempted"] == [
        "get_order_by_exchange_order_id",
        "list_orders_by_product_id_match_client_or_exchange_order_id",
    ]
    assert report["coinbase_lookup_succeeded_method"] == ""
    assert report["order_id_used"] == "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"
    assert report["client_order_id_used"] == "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    assert report["product_id_used"] == "BTC-USDC"
    assert report["include_fills"] is True
    assert report["fallback_attempted"] is True
    assert report["fallback_succeeded"] is False
    assert report["cancel_attempted"] is False
    assert report["replace_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False
    assert client.cancelled == []
    assert client.replaced == []


def test_coinbase_non_open_routes_away(tmp_path: Path, monkeypatch) -> None:
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("filled", filled_base="0.00006489", fill_count=1, remaining_size="0"),
        allow_coinbase_poll=True,
    )
    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert report["preflight_status"] == "cancel_replace_pilot_preflight_not_applicable_lifecycle_evidence_available"


def test_cancel_fails_no_replace(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient(cancel_exc=RuntimeError("cancel boom"))
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_cancel_failed_no_replace"
    assert report["cancel_attempted"] is True
    assert report["replace_attempted"] is False
    assert report["state_write_performed"] is False


def test_cancel_uncertain_blocks_replace(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient(cancel_response={"success": True, "order_ids": []})
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_cancel_uncertain_no_replace"
    assert report["cancel_attempted"] is True
    assert report["replace_attempted"] is False


def test_cancel_success_and_replace_success_update_state(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient(
        cancel_response={"success": True, "order_ids": ["bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"]},
        replace_response={"success": True, "order_id": "repl-order-1"},
    )
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_applied"
    assert report["cancel_attempted"] is True
    assert report["replace_attempted"] is True
    assert report["state_write_performed"] is True
    assert report["local_old_order_status_after"] == "cancelled"
    assert report["local_new_order_status_after"] == "submitted"
    assert report["local_position_status_after"] == "open"
    assert report["reserved_base_open_exit_orders_after"] == "0.00006489"
    assert report["duplicate_open_d3_exit_detected_after"] is False
    assert report["oversell_detected_after"] is False


def test_replacement_submit_fail_requires_manual_review(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient(
        cancel_response={"success": True, "order_ids": ["bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"]},
        replace_exc=RuntimeError("replace boom"),
    )
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
    )

    assert report["status"] == "cancel_replace_pilot_replace_failed_manual_review_required"
    assert report["replace_attempted"] is True
    assert report["state_write_performed"] is False


def test_min_size_blocks_replacement(tmp_path: Path, monkeypatch) -> None:
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        client=FakeCoinbaseClient(),
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
        position_kwargs={"effective_min_trade_base": "0.001"},
    )

    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert "replacement_below_min_size" in report["blockers"]


def test_duplicate_open_exit_before_replacement_blocks(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-6T0949383258879999",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f32",
    )

    report = run_phase_d3_cancel_replace_pilot(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        cfg=_Cfg(),
        order_store=orders,
        state_store=state,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
    )

    assert report["status"] == "cancel_replace_pilot_preview_blocked"
    assert report["preflight_status"] == "cancel_replace_pilot_preflight_blocked_safety"


def test_no_market_or_taker_replacement_allowed(tmp_path: Path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("open"), allow_coinbase_poll=True)
    assert report["replace_side"] == "SELL"
    assert report["replace_post_only"] is True
    assert report["replace_reduce_only_semantic"] is True


def test_state_idempotency_no_duplicate_replacement_after_success(tmp_path: Path, monkeypatch) -> None:
    client = FakeCoinbaseClient(
        cancel_response={"success": True, "order_ids": ["bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"]},
        replace_response={"success": True, "order_id": "repl-order-1"},
    )
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    first = run_phase_d3_cancel_replace_pilot(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        cfg=_Cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
        snapshot=_snapshot("open"),
    )
    second = run_phase_d3_cancel_replace_pilot(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        cfg=_Cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
        allow_coinbase_poll=True,
        allow_live_cancel=True,
        allow_live_replace=True,
        pilot_ack=D3_CANCEL_REPLACE_PILOT_ACK,
        snapshot=_snapshot("open"),
    )

    assert first["status"] == "cancel_replace_pilot_applied"
    assert second["status"] == "cancel_replace_pilot_already_applied_noop"
    assert len(client.replaced) == 1
