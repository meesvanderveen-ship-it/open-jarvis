from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_open_exit_monitor import build_phase_d3_open_exit_monitor_report
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


def _seed_position(state: StateStore, *, status: str = "open", position_size_base: str = "0.0000649067431275", reserved: str = "0.00006489", bot_managed: str = "0.0001297967431275") -> None:
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


def _seed_open_exit(orders: OrderStore, *, client_order_id: str = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000", exchange_order_id: str = "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31", linked_position_id: str = "76310097-849e-481c-b587-ba44bc3330fe", created_at: str = "2026-05-26T17:00:00+00:00") -> None:
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


def _report(tmp_path: Path, monkeypatch, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    return build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def test_local_coherent_without_coinbase_poll_keeps_monitoring(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch)

    assert report["status"] == "open_exit_monitor_local_coherent"
    assert report["operator_decision"] == "keep_monitoring"
    assert report["next_allowed_action"] == "read_only_coinbase_poll_later"
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["live_action_performed"] is False


def test_local_coherent_with_coinbase_open_keeps_open_and_monitor(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("open"),
    )

    assert report["status"] == "open_exit_monitor_coinbase_open"
    assert report["operator_decision"] == "keep_open_and_monitor"
    assert report["coinbase_normalized_status"] == "open"
    assert report["next_allowed_action"] in {"later_read_only_poll", "read_only_poll_later_with_stale_watch", "stale_open_review_later"}
    assert report["no_coinbase_submit"] is True


def test_local_position_drift_requires_recovery_if_coinbase_open(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", reserved="0.00006489", bot_managed="0")
    _seed_open_exit(orders)

    report = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "open_exit_monitor_local_position_drift"
    assert report["operator_decision"] == "recovery_required_if_coinbase_open"
    assert report["priority_classification"] == "P1"
    assert report["live_action_performed"] is False


def test_coinbase_partial_evidence_awaits_explicit_apply_approval(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("partially_filled", filled_base="0.00001", filled_quote="0.82", avg_fill_price="82000", fill_count=1, remaining_size="0.00005489"),
    )

    assert report["status"] == "open_exit_monitor_lifecycle_evidence_available"
    assert report["operator_decision"] == "await_explicit_lifecycle_apply_approval"
    assert report["coinbase_normalized_status"] == "partially_filled"


def test_coinbase_filled_evidence_awaits_explicit_apply_approval(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        snapshot=_snapshot("filled", filled_base="0.00006489", filled_quote="5.29", avg_fill_price="81664.97", fill_count=1, remaining_size="0"),
    )

    assert report["status"] == "open_exit_monitor_lifecycle_evidence_available"
    assert report["operator_decision"] == "await_explicit_lifecycle_apply_approval"
    assert report["coinbase_normalized_status"] == "filled"


def test_terminal_coinbase_evidence_awaits_explicit_apply_approval(tmp_path: Path, monkeypatch) -> None:
    for status in ("cancelled", "expired", "rejected"):
        report = _report(
            tmp_path,
            monkeypatch,
            allow_coinbase_poll=True,
            snapshot=_snapshot(status, remaining_size="0"),
        )
        assert report["status"] == "open_exit_monitor_lifecycle_evidence_available"
        assert report["operator_decision"] == "await_explicit_lifecycle_apply_approval"
        assert report["coinbase_normalized_status"] == status


def test_coinbase_poll_failure_surfaces_diagnostics_without_live_action(tmp_path: Path, monkeypatch) -> None:
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
            coinbase_order_lookup_method_attempted=["get_order_by_exchange_order_id"],
            warnings=["coinbase_poll_failed:RuntimeError"],
            blockers=["coinbase_snapshot_unavailable"],
        ),
    )

    assert report["status"] == "open_exit_monitor_coinbase_poll_failed"
    assert report["operator_decision"] == "retry_later_or_use_outside_sandbox_read_only_poll"
    assert report["coinbase_errors"]["type"] == "RuntimeError"
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

    report = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "open_exit_monitor_blocked_review_required"
    assert report["duplicate_open_d3_exit_detected"] is True


def test_stale_open_age_classification(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 5, 26, 17, 30, tzinfo=timezone.utc)
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)

    _seed_open_exit(orders, created_at=(now - timedelta(minutes=10)).isoformat())
    normal = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert normal["stale_open_classification"] == "normal_monitoring"

    orders.update_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000", {"created_at": (now - timedelta(minutes=60)).isoformat(), "submitted_at": (now - timedelta(minutes=60)).isoformat()})
    watch = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert watch["stale_open_classification"] == "stale_watch"

    orders.update_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000", {"created_at": (now - timedelta(minutes=180)).isoformat(), "submitted_at": (now - timedelta(minutes=180)).isoformat()})
    stale = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert stale["stale_open_classification"] == "stale_open_review_recommended"

    orders.update_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000", {"created_at": "", "submitted_at": ""})
    unknown = build_phase_d3_open_exit_monitor_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        now=now,
    )
    assert unknown["stale_open_classification"] == "stale_age_unknown"
