from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_pilot_preflight import (
    build_phase_d3_cancel_replace_pilot_preflight_report,
)
from bot.phase_d3_cancel_replace_review import D3_CANCEL_REPLACE_PILOT_ACK
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


def _seed_position(
    state: StateStore,
    *,
    status: str = "open",
    position_size_base: str = "0.0000649067431275",
    reserved: str = "0.00006489",
    bot_managed: str = "0.0001297967431275",
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
) -> None:
    orders.upsert_order(
        {
            "client_order_id": client_order_id,
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
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


class _RejectWriteClient:
    def cancel_order(self, *args, **kwargs):
        raise AssertionError("cancel must not be called")

    def place_limit_order(self, *args, **kwargs):
        raise AssertionError("submit must not be called")


class _RuntimeErrorClient(_RejectWriteClient):
    def get_order(self, order_id):
        raise RuntimeError("simulated get_order failure")

    def list_orders(self, product_id=None, order_status=None, limit=100, cursor=None):
        raise RuntimeError("simulated list_orders failure")

    def get_recent_fills_for_order(self, order_id, limit=100):
        raise AssertionError("fills should not be called after lookup failure")


def _report(tmp_path: Path, monkeypatch, *, limit_price: str = "81664.97", **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders, limit_price=limit_price)
    return build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def test_local_only_preflight_needs_fresh_open_evidence(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, now=datetime(2026, 5, 26, 18, 0, tzinfo=timezone.utc))

    assert report["status"] == "cancel_replace_pilot_preflight_needs_fresh_open_evidence"
    assert report["preflight_decision"] == "run_one_read_only_coinbase_poll_before_pilot"
    assert report["pilot_candidate_ready"] is False
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_submit"] is True


def test_coinbase_open_with_candidate_price_is_ready(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
    )

    assert report["status"] == "cancel_replace_pilot_preflight_ready"
    assert report["preflight_decision"] == "ready_for_explicit_cancel_replace_pilot_approval"
    assert report["pilot_candidate_ready"] is True
    assert report["cancel_leg_ready"] is True
    assert report["replace_leg_ready"] is True
    assert report["candidate_cancel_order_id"] == "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"
    assert report["candidate_cancel_client_order_id"] == "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    assert report["candidate_replace_side"] == "SELL"
    assert report["candidate_replace_size_base"] == "0.00006489"
    assert report["candidate_replace_limit_price"] == "81664.97"
    assert report["required_ack_for_future_pilot"] == D3_CANCEL_REPLACE_PILOT_ACK


def test_coinbase_open_without_price_needs_price_context(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
        limit_price="",
    )

    assert report["status"] == "cancel_replace_pilot_preflight_needs_price_context"
    assert report["preflight_decision"] == "collect_read_only_price_context_before_pilot"
    assert report["pilot_candidate_ready"] is False
    assert report["cancel_leg_ready"] is True
    assert report["replace_leg_ready"] is False
    assert report["candidate_replace_requires_fresh_price"] is True


def test_coinbase_partial_or_filled_routes_to_lifecycle_apply(tmp_path: Path, monkeypatch) -> None:
    for status, base in (("partially_filled", "0.00001"), ("filled", "0.00006489")):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, filled_base=base, fill_count=1, remaining_size="0.00005489" if status == "partially_filled" else "0"),
        )
        assert report["status"] == "cancel_replace_pilot_preflight_not_applicable_lifecycle_evidence_available"
        assert report["preflight_decision"] == "route_to_controlled_lifecycle_apply"


def test_coinbase_terminal_non_open_routes_to_lifecycle_apply(tmp_path: Path, monkeypatch) -> None:
    for status in ("cancelled", "expired", "rejected"):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, remaining_size="0"),
        )
        assert report["status"] == "cancel_replace_pilot_preflight_not_applicable_lifecycle_evidence_available"
        assert report["preflight_decision"] == "route_to_controlled_lifecycle_apply"


def test_local_position_drift_blocks_preflight(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", reserved="0.00006489", bot_managed="0")
    _seed_open_exit(orders)

    report = build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_pilot_preflight_blocked_local_position_drift"
    assert report["preflight_decision"] == "recovery_required_if_coinbase_open"


def test_duplicate_open_d3_exits_block_preflight(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-6T0949383258879999",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f32",
    )

    report = build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_pilot_preflight_blocked_safety"


def test_oversell_or_reservation_mismatch_blocks_preflight(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        limit_price="81664.97",
    )
    assert report["reservation_covers_remaining_size"] is True

    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, position_size_base="0.00001", reserved="0.000001", bot_managed="0.00001")
    _seed_open_exit(orders)
    blocked = build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )
    assert blocked["status"] == "cancel_replace_pilot_preflight_blocked_safety"


def test_poll_failure_branch(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot(
            "",
            coinbase_call_succeeded=False,
            coinbase_snapshot_unavailable=True,
            coinbase_error_type="RuntimeError",
            coinbase_error_message="dns failed",
            coinbase_error_stage="lookup_order",
            warnings=["coinbase_poll_failed:RuntimeError"],
            blockers=["coinbase_snapshot_unavailable"],
        ),
    )

    assert report["status"] == "cancel_replace_pilot_preflight_coinbase_poll_failed"
    assert report["preflight_decision"] == "retry_later_or_use_outside_sandbox_read_only_poll"


def test_runtime_error_poll_failure_exposes_lookup_diagnostics(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        coinbase_client=_RuntimeErrorClient(),
    )

    assert report["status"] == "cancel_replace_pilot_preflight_coinbase_poll_failed"
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
    assert [row["method"] for row in report["coinbase_lookup_failed_methods"]] == [
        "get_order_by_exchange_order_id",
        "list_orders_by_product_id_match_client_or_exchange_order_id",
    ]
    assert report["order_id_used"] == "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"
    assert report["client_order_id_used"] == "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    assert report["product_id_used"] == "BTC-USDC"
    assert report["include_fills"] is True
    assert report["fallback_attempted"] is True
    assert report["fallback_succeeded"] is False
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_submit"] is True
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False


def test_candidate_fields_are_consistent(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
    )

    assert report["candidate_cancel_order_id"] == "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31"
    assert report["candidate_cancel_client_order_id"] == "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    assert report["candidate_replace_side"] == "SELL"
    assert report["candidate_replace_size_base"] == "0.00006489"
    assert report["candidate_replace_post_only"] is True
    assert report["candidate_replace_reduce_only_semantic"] is True
    assert report["required_ack_for_future_pilot"] == D3_CANCEL_REPLACE_PILOT_ACK
