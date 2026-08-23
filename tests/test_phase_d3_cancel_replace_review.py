from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_review import (
    D3_CANCEL_REPLACE_PILOT_ACK,
    build_phase_d3_cancel_replace_review_report,
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
    created_at: str = "2026-05-26T09:00:00+00:00",
    remaining_size: str = "0.00006489",
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
            "limit_price": "81664.97",
            "created_at": created_at,
            "submitted_at": created_at,
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


def _report(tmp_path: Path, monkeypatch, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    return build_phase_d3_cancel_replace_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def test_local_only_coherent_review_needs_fresh_open_evidence(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, now=datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc))

    assert report["status"] == "cancel_replace_review_needs_fresh_open_evidence"
    assert report["cancel_replace_decision"] == "run_one_read_only_coinbase_poll_before_pilot"
    assert report["next_allowed_action"] == "read_only_coinbase_poll"
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False


def test_coherent_coinbase_open_review_is_ready_for_future_pilot(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
        now=datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc),
    )

    assert report["status"] == "cancel_replace_review_ready"
    assert report["cancel_replace_decision"] == "prepare_cancel_replace_pilot"
    assert report["recommended_operator_branch"] == "Controlled D.3 Cancel/Replace Review v1"
    assert report["candidate_cancel_allowed_in_future"] is True
    assert report["candidate_replace_allowed_in_future"] is True
    assert report["candidate_replace_side"] == "SELL"
    assert report["candidate_replace_size_base"] == "0.00006489"
    assert report["candidate_replace_limit_price"] == "81664.97"
    assert report["required_future_ack"] == D3_CANCEL_REPLACE_PILOT_ACK


def test_coinbase_partial_or_filled_routes_to_controlled_lifecycle_apply(tmp_path: Path, monkeypatch) -> None:
    for status, base in (("partially_filled", "0.00001"), ("filled", "0.00006489")):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, filled_base=base, filled_quote="0.82", avg_fill_price="82000", fill_count=1, remaining_size="0.00005489" if status == "partially_filled" else "0"),
        )
        assert report["status"] == "cancel_replace_review_not_applicable_lifecycle_evidence_available"
        assert report["cancel_replace_decision"] == "route_to_controlled_lifecycle_apply"


def test_coinbase_terminal_non_open_routes_to_controlled_lifecycle_apply(tmp_path: Path, monkeypatch) -> None:
    for status in ("cancelled", "expired", "rejected"):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, remaining_size="0"),
        )
        assert report["status"] == "cancel_replace_review_not_applicable_lifecycle_evidence_available"
        assert report["cancel_replace_decision"] == "route_to_controlled_lifecycle_apply"


def test_local_position_drift_blocks_cancel_replace_review(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", reserved="0.00006489", bot_managed="0")
    _seed_open_exit(orders)

    report = build_phase_d3_cancel_replace_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_review_blocked_local_position_drift"
    assert report["cancel_replace_decision"] == "recovery_required_if_coinbase_open"


def test_duplicate_open_d3_exits_block_safety_review(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-6T0949383258879999",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f32",
    )

    report = build_phase_d3_cancel_replace_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_review_blocked_safety"
    assert report["priority_classification"] == "P0"


def test_oversell_reservation_mismatch_blocks_safety_review(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, position_size_base="0.00001", reserved="0.00006489", bot_managed="0.00001")
    _seed_open_exit(orders)

    report = build_phase_d3_cancel_replace_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_review_blocked_safety"
    assert report["oversell_detected"] is True


def test_coinbase_poll_failure_returns_poll_failed_branch(tmp_path: Path, monkeypatch) -> None:
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

    assert report["status"] == "cancel_replace_review_coinbase_poll_failed"
    assert report["next_allowed_action"] == "read_only_coinbase_poll_later_or_outside_sandbox"


def test_candidate_fields_are_consistent_for_open_review(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
        now=datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc),
    )

    assert report["candidate_replace_size_base"] == "0.00006489"
    assert report["candidate_replace_side"] == "SELL"
    assert report["candidate_replace_post_only"] is True
    assert report["candidate_replace_reduce_only_semantic"] is True
    assert report["required_future_ack"] == D3_CANCEL_REPLACE_PILOT_ACK
