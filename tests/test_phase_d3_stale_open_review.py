from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_stale_open_review import build_phase_d3_stale_open_review_report
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
            "size_base": "0.00006489",
            "remaining_size": "0.00006489",
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


def _report(tmp_path: Path, monkeypatch, *, now: datetime | None = None, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    return build_phase_d3_stale_open_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
        **kwargs,
    )


def test_local_only_stale_review_recommends_one_read_only_poll(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc)
    report = _report(tmp_path, monkeypatch, now=now)

    assert report["status"] == "stale_open_review_local_only_ready"
    assert report["stale_review_decision"] == "read_only_coinbase_poll_recommended_before_any_action"
    assert report["recommended_operator_branch"] == "run_one_read_only_coinbase_poll"
    assert report["next_allowed_action"] == "read_only_coinbase_poll"
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False


def test_coinbase_open_recommends_cancel_replace_review_later(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc)
    report = _report(
        tmp_path,
        monkeypatch,
        now=now,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
    )

    assert report["status"] == "stale_open_review_coinbase_open"
    assert report["stale_review_decision"] == "prepare_cancel_replace_review_later"
    assert report["recommended_operator_branch"] == "Controlled D.3 Cancel/Replace Review v1"
    assert report["next_allowed_action"] == "prepare_cancel_replace_review_only"


def test_coinbase_partial_routes_to_lifecycle_apply_branch(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("partially_filled", filled_base="0.00001", filled_quote="0.82", avg_fill_price="82000", fill_count=1, remaining_size="0.00005489"),
    )

    assert report["status"] == "stale_open_review_lifecycle_evidence_available"
    assert report["stale_review_decision"] == "await_explicit_d3_lifecycle_apply_approval"
    assert report["recommended_operator_branch"] == "Controlled D.3 lifecycle apply on real evidence"


def test_coinbase_filled_routes_to_lifecycle_apply_branch(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("filled", filled_base="0.00006489", filled_quote="5.29", avg_fill_price="81664.97", fill_count=1, remaining_size="0"),
    )

    assert report["status"] == "stale_open_review_lifecycle_evidence_available"
    assert report["stale_review_decision"] == "await_explicit_d3_lifecycle_apply_approval"


def test_terminal_coinbase_statuses_route_to_lifecycle_apply_branch(tmp_path: Path, monkeypatch) -> None:
    for status in ("cancelled", "expired", "rejected"):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, remaining_size="0"),
        )
        assert report["status"] == "stale_open_review_lifecycle_evidence_available"
        assert report["recommended_operator_branch"] == "Controlled D.3 lifecycle apply on real evidence"


def test_local_position_drift_requires_recovery_if_open(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", reserved="0.00006489", bot_managed="0")
    _seed_open_exit(orders)

    report = build_phase_d3_stale_open_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "stale_open_review_local_position_drift"
    assert report["stale_review_decision"] == "recovery_required_if_coinbase_open"


def test_coinbase_poll_failure_recommends_retry_later(tmp_path: Path, monkeypatch) -> None:
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

    assert report["status"] == "stale_open_review_coinbase_poll_failed"
    assert report["stale_review_decision"] == "retry_later_or_use_outside_sandbox_read_only_poll"
    assert report["live_action_performed"] is False


def test_duplicate_open_d3_exits_block_review(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-6T0949383258879999",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f32",
    )

    report = build_phase_d3_stale_open_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "stale_open_review_blocked_review_required"


def test_stale_age_not_recommended_yet_keeps_monitoring(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc)
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)

    _seed_open_exit(orders, created_at=(now - timedelta(minutes=10)).isoformat())
    normal = build_phase_d3_stale_open_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert normal["status"] == "stale_open_review_not_needed_yet"
    assert normal["stale_review_decision"] == "keep_monitoring"

    orders.update_order(
        "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        {
            "created_at": (now - timedelta(minutes=60)).isoformat(),
            "submitted_at": (now - timedelta(minutes=60)).isoformat(),
        },
    )
    watch = build_phase_d3_stale_open_review_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert watch["status"] == "stale_open_review_not_needed_yet"
    assert watch["next_allowed_action"] == "read_only_coinbase_poll_later"
