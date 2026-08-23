from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY
from bot.phase_d3_controlled_live_exits import assess_phase_d3_exit_readiness
from bot.order_store import OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import (
    D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    build_phase_d3_open_exit_lifecycle_report,
    scan_open_d3_exit_lifecycle_orders,
)
from bot.state_store import StateStore


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    monkeypatch.setenv("ENABLE_LIVE_EXIT_ORDERS", "false")
    monkeypatch.setenv("AUTONOMOUS_ALLOW_EXITS", "false")
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _seed_open_position(state: StateStore) -> None:
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "open",
            "order_id": "pos-1",
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_size_base": "0.0000649067431275",
            "position_size_quote": "4.9701704868084948825",
            "bot_managed_base": "0.0001297967431275",
            "reserved_base_open_exit_orders": "0.00006489",
            "partial_take_profit_taken": True,
            "monitoring_enabled": True,
        },
    )


def _seed_open_exit(
    orders: OrderStore,
    *,
    client_order_id: str = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
    exchange_order_id: str = "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
    linked_position_id: str = "76310097-849e-481c-b587-ba44bc3330fe",
    status: str = "submitted",
    size_base: str = "0.00006489",
    remaining_size: str = "0.00006489",
    filled_base: str = "0",
    filled_quote: str = "0",
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
            "size_base": size_base,
            "remaining_size": remaining_size,
            "filled_base": filled_base,
            "filled_quote": filled_quote,
            "fill_count": fill_count,
            "limit_price": "81664.97",
        }
    )


def _snapshot(status: str, **overrides):
    payload = {
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": True,
        "raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "fees": "0",
    }
    payload.update(overrides)
    return payload


def _report(tmp_path: Path, monkeypatch, **kwargs):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders)
    return build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def test_position_risk_incomplete_blocks_live_d2_d3_exit_readiness(tmp_path: Path) -> None:
    orders = _orders(tmp_path)
    readiness = assess_phase_d3_exit_readiness(
        cfg=SimpleNamespace(
            enable_phase_d3_controlled_live_exits=True,
            phase_c_allowed_tickers=["BTC-USDC"],
            phase_d3_max_exit_order_quote="100.00",
            phase_d3_max_open_exit_orders=4,
            phase_d3_max_new_exit_orders_per_cycle=1,
            enable_phase_d3_actual_exit_submit=True,
            enable_live_exit_orders=True,
            autonomous_allow_exits=True,
            phase_c_disable_exit_limit_orders=False,
            phase_d3_exit_order_post_only=True,
            phase_d3_require_reduce_only_local=True,
        ),
        position={
            "ticker": "BTC-USDC",
            "status": "open",
            "order_id": "pos-risk-incomplete",
            "position_size_base": "0.01",
            "bot_managed_base": "0.01",
            "entry_price": "50000",
            "stop_price": "49000",
            "invalidation_price": "0",
            "protective_stop_status": "position_risk_incomplete",
            "position_risk_incomplete": True,
        },
        plan={
            "ticker": "BTC-USDC",
            "status": D2_PLAN_STATUS_READY,
            "position_id": "pos-risk-incomplete",
        },
        exit_intent={
            "ticker": "BTC-USDC",
            "position_id": "pos-risk-incomplete",
            "side": "SELL",
            "execution_action": "place_limit_sell",
            "size_base": "0.005",
            "limit_price": "51000",
            "reduce_only_local": True,
            "label": "TP1",
        },
        order_store=orders,
        human_ack="",
        submit_live=False,
    )
    assert readiness["ready"] is False
    assert "position_risk_incomplete_stop_or_invalidation_missing" in readiness["blockers"]
    assert readiness["submit_armed"] is False


class _RejectWriteClient:
    def place_limit_order(self, *args, **kwargs):
        raise AssertionError("submit must not be called")

    def place_market_order(self, *args, **kwargs):
        raise AssertionError("submit must not be called")


class _RuntimeErrorClient(_RejectWriteClient):
    def get_order(self, order_id):
        raise RuntimeError("simulated get_order failure")

    def list_orders(self, product_id=None, order_status=None, limit=100, cursor=None):
        raise RuntimeError("simulated list_orders failure")

    def get_recent_fills_for_order(self, order_id, limit=100):
        raise AssertionError("fills should not be called after get_order failure")


class _FallbackClient(_RejectWriteClient):
    def __init__(self, *, fills_error: bool = False):
        self.fills_error = fills_error

    def get_order(self, order_id):
        raise RuntimeError("primary lookup failed")

    def list_orders(self, product_id=None, order_status=None, limit=100, cursor=None):
        return {
            "orders": [
                {
                    "order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
                    "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
                    "product_id": "BTC-USDC",
                    "side": "SELL",
                    "status": "OPEN",
                    "filled_size": "0",
                }
            ]
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        if self.fills_error:
            raise RuntimeError("fills lookup failed")
        return []


class _OpenOrderClient(_RejectWriteClient):
    def get_order(self, order_id):
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "filled_size": "0",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


def test_preview_only_keeps_local_open_without_coinbase_poll(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch)

    assert report["status"] == "d3_open_exit_lifecycle_preview_ready"
    assert report["mode"] == "preview"
    assert report["coinbase_call_attempted"] is False
    assert report["proposed_action"] == "keep_local_open_no_live_snapshot"
    assert report["state_write_performed"] is False
    assert report["no_state_write"] is True
    assert report["duplicate_exit_detected"] is False
    assert report["oversell_detected"] is False
    assert report["reservation_before"] == "0.00006489"
    assert report["reservation_after_preview"] == "0.00006489"
    assert not (tmp_path / "state" / "runtime_mutation.lock").exists()


def test_blocks_when_matching_order_is_missing(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)

    report = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert "matching_open_d3_order_not_found" in report["blockers"]


def test_blocks_duplicate_open_d3_orders_for_same_logical_position(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-6T0949383258879999",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f32",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
    )

    report = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert report["duplicate_exit_detected"] is True
    assert "duplicate_open_d3_exit_order_for_position" in report["blockers"]


def test_apply_requires_ack(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("cancelled"),
        apply_local=True,
    )

    assert report["status"] == "blocked_review_required"
    assert "d3_open_exit_lifecycle_apply_ack_required" in report["blockers"]
    assert report["state_write_performed"] is False
    assert not (tmp_path / "state" / "runtime_mutation.lock").exists()


def test_open_apply_is_noop_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    first = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    second = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    state = StateStore()
    orders = _orders(tmp_path)
    position = state.get_position("BTC-USDC")
    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert first["status"] == "d3_open_exit_lifecycle_applied_noop"
    assert first["mutation_lock"] == {"acquired": True, "reentrant": False}
    assert first["proposed_action"] == "keep_open"
    assert first["state_write_performed"] is False
    assert second["status"] == "d3_open_exit_lifecycle_applied_noop"
    assert second["state_write_performed"] is False
    assert position["status"] == "open"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["reserved_base_open_exit_orders"] == "0.00006489"
    assert order["status"] == "submitted"
    assert order["remaining_size"] == "0.00006489"


def test_apply_partial_fill_reduces_exactly_once_and_sets_idempotency_metadata(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot(
            "partially_filled",
            filled_base="0.00001",
            filled_quote="0.82",
            avg_fill_price="82000",
            fill_count=1,
            remaining_size="0.00005489",
        ),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    state = StateStore()
    orders = _orders(tmp_path)
    position = state.get_position("BTC-USDC")
    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert report["status"] == "d3_open_exit_lifecycle_applied"
    assert report["proposed_action"] == "mark_partially_filled"
    assert report["state_write_performed"] is True
    assert order["status"] == "partially_filled"
    assert order["remaining_size"] == "0.00005489"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["bot_managed_base"] == "0.0001197967431275"
    assert order["last_d3_exit_lifecycle_applied_status"] == "partially_filled"
    assert order["last_d3_exit_lifecycle_applied_filled_base"] == "0.00001"


def test_apply_partial_fill_same_evidence_is_idempotent_noop(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(
        "partially_filled",
        filled_base="0.00001",
        filled_quote="0.82",
        avg_fill_price="82000",
        fill_count=1,
        remaining_size="0.00005489",
    )
    first = _report(
        tmp_path,
        monkeypatch,
        snapshot=snapshot,
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    second = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=_orders(tmp_path),
        state_store=StateStore(),
        snapshot=snapshot,
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    position = StateStore().get_position("BTC-USDC")

    assert first["status"] == "d3_open_exit_lifecycle_applied"
    assert second["status"] == "d3_open_exit_lifecycle_apply_idempotent_noop"
    assert second["proposed_action"] == "already_applied_noop"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["bot_managed_base"] == "0.0001197967431275"


def test_apply_cancelled_releases_reservation_and_keeps_position_open(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("cancelled"),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    state = StateStore()
    orders = _orders(tmp_path)
    position = state.get_position("BTC-USDC")
    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert report["status"] == "d3_open_exit_lifecycle_applied"
    assert report["proposed_action"] == "mark_cancelled"
    assert report["state_write_performed"] is True
    assert position["status"] == "open"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["bot_managed_base"] == "0.0001297967431275"
    assert order["status"] == "cancelled"
    assert order["remaining_size"] == "0"
    assert order["last_d3_exit_lifecycle_applied_status"] == "cancelled"
    assert orders.open_exit_orders("BTC-USDC") == []


def test_apply_expired_releases_reservation_and_keeps_position_open(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("expired", remaining_size="0"),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    order = _orders(tmp_path).get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")
    position = StateStore().get_position("BTC-USDC")

    assert report["status"] == "d3_open_exit_lifecycle_applied"
    assert report["proposed_action"] == "mark_expired"
    assert order["status"] == "expired"
    assert order["remaining_size"] == "0"
    assert position["status"] == "open"


def test_apply_rejected_releases_reservation_and_keeps_position_open(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("rejected", remaining_size="0"),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    order = _orders(tmp_path).get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")
    position = StateStore().get_position("BTC-USDC")

    assert report["status"] == "d3_open_exit_lifecycle_applied"
    assert report["proposed_action"] == "mark_rejected"
    assert order["status"] == "rejected"
    assert order["remaining_size"] == "0"
    assert position["status"] == "open"


def test_apply_filled_reduces_position_and_finalizes_order(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot(
            "filled",
            filled_base="0.00006489",
            filled_quote="5.2989357533",
            avg_fill_price="81664.97",
            fill_count=1,
            remaining_size="0",
        ),
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    state = StateStore()
    orders = _orders(tmp_path)
    position = state.get_position("BTC-USDC")
    order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert report["status"] == "d3_open_exit_lifecycle_applied"
    assert report["proposed_action"] == "mark_filled"
    assert report["state_write_performed"] is True
    assert position["status"] == "open"
    assert position["position_size_base"] == "0.0000649067431275"
    assert position["bot_managed_base"] == "0.0000649067431275"
    assert order["status"] == "filled"
    assert order["remaining_size"] == "0"
    assert order["last_d3_exit_lifecycle_applied_status"] == "filled"


def test_apply_filled_same_evidence_is_idempotent_noop(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(
        "filled",
        filled_base="0.00006489",
        filled_quote="5.2989357533",
        avg_fill_price="81664.97",
        fill_count=1,
        remaining_size="0",
    )
    first = _report(
        tmp_path,
        monkeypatch,
        snapshot=snapshot,
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )
    second = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=_orders(tmp_path),
        state_store=StateStore(),
        snapshot=snapshot,
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )

    assert first["status"] == "d3_open_exit_lifecycle_applied"
    assert second["status"] == "d3_open_exit_lifecycle_apply_idempotent_noop"
    assert second["state_write_performed"] is False


def test_blocks_unknown_status_snapshot(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("unknown"),
    )

    assert report["status"] == "blocked_review_required"
    assert "unknown_coinbase_order_status" in report["blockers"]


def test_coinbase_runtime_error_surfaces_diagnostics(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        coinbase_client=_RuntimeErrorClient(),
    )

    assert report["status"] == "blocked_review_required"
    assert "coinbase_snapshot_unavailable" in report["blockers"]
    assert report["coinbase_call_attempted"] is True
    assert report["coinbase_call_succeeded"] is False
    assert report["coinbase_error_type"] == "RuntimeError"
    assert "simulated list_orders failure" in report["coinbase_error_message"]
    assert report["coinbase_error_stage"] == "lookup_order"
    assert report["coinbase_order_lookup_method_attempted"] == ["get_order_by_exchange_order_id", "list_orders_by_product_id_match_client_or_exchange_order_id"]
    assert [row["method"] for row in report["coinbase_order_lookup_failed_methods"]] == [
        "get_order_by_exchange_order_id",
        "list_orders_by_product_id_match_client_or_exchange_order_id",
    ]
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["state_write_performed"] is False


def test_exchange_order_lookup_success_sets_open_proposed_action(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        coinbase_client=_OpenOrderClient(),
    )

    assert report["status"] == "d3_open_exit_lifecycle_keep_open_preview"
    assert report["normalized_status"] == "open"
    assert report["proposed_action"] == "keep_open"
    assert report["coinbase_order_lookup_succeeded_method"] == "get_order_by_exchange_order_id"
    assert report["state_write_performed"] is False


def test_open_d3_order_is_found_by_lifecycle_scan(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(
        orders,
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
        exchange_order_id="81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        size_base="0.00015416",
        remaining_size="0.00015416",
    )

    found = scan_open_d3_exit_lifecycle_orders(orders, ticker="BTC-USDC")

    assert len(found) == 1
    assert found[0]["client_order_id"] == "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000"
    assert found[0]["exchange_order_id"] == "81edc268-cf15-4f25-b30b-f0d5b3abb30d"
    assert found[0]["linked_position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"


def test_open_status_d3_order_is_found_by_lifecycle_scan(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders, status="open")

    found = scan_open_d3_exit_lifecycle_orders(orders, ticker="BTC-USDC")

    assert len(found) == 1
    assert found[0]["status"] == "open"


def test_missing_exchange_order_id_blocks_d3_lifecycle(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    client_order_id = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000"
    orders._write_state(
        {
            "orders": {
                client_order_id: {
                    "client_order_id": client_order_id,
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "status": "submitted",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
                    "exchange_order_id": "",
                    "order_id": "",
                    "execution_action": "place_limit_sell",
                    "d3_exit_label": "TP1",
                    "size_base": "0.00006489",
                    "remaining_size": "0.00006489",
                    "filled_base": "0",
                    "filled_quote": "0",
                    "fill_count": 0,
                    "limit_price": "81664.97",
                }
            }
        }
    )

    report = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id=client_order_id,
        exchange_order_id="",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert "exchange_order_id_required_for_d3_lifecycle" in report["blockers"]


def test_coinbase_open_keeps_open_and_does_not_write_state(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open", coinbase_call_attempted=True),
        apply_local=False,
    )

    assert report["status"] == "d3_open_exit_lifecycle_keep_open_preview"
    assert report["normalized_status"] == "open"
    assert report["proposed_action"] == "keep_open"
    assert report["state_write_performed"] is False
    assert report["no_state_write"] is True


def test_coinbase_filled_proposes_apply_without_ack_but_does_not_apply(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot(
            "filled",
            coinbase_call_attempted=True,
            filled_base="0.00006489",
            filled_quote="5.2989357533",
            avg_fill_price="81664.97",
            fill_count=1,
            remaining_size="0",
        ),
        apply_local=False,
    )
    order = _orders(tmp_path).get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000")

    assert report["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
    assert report["normalized_status"] == "filled"
    assert report["proposed_action"] == "mark_filled"
    assert report["state_write_performed"] is False
    assert order["status"] == "submitted"


def test_exchange_lookup_failure_falls_back_to_list_orders(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        coinbase_client=_FallbackClient(),
    )

    assert report["status"] == "d3_open_exit_lifecycle_keep_open_preview"
    assert report["normalized_status"] == "open"
    assert report["coinbase_order_lookup_method_attempted"] == [
        "get_order_by_exchange_order_id",
        "list_orders_by_product_id_match_client_or_exchange_order_id",
        "list_fills_by_exchange_order_id",
    ]
    assert report["coinbase_order_lookup_succeeded_method"] == "list_orders_by_product_id_match_client_or_exchange_order_id"
    assert report["state_write_performed"] is False


def test_include_fills_failure_uses_status_only_open_evidence(tmp_path: Path, monkeypatch) -> None:
    report = _report(
        tmp_path,
        monkeypatch,
        allow_coinbase_poll=True,
        coinbase_client=_FallbackClient(fills_error=True),
    )

    assert report["status"] == "d3_open_exit_lifecycle_keep_open_preview"
    assert report["normalized_status"] == "open"
    assert report["proposed_action"] == "keep_open_status_only_evidence"
    assert "coinbase_fills_lookup_failed:RuntimeError" in report["warnings"]
    assert report["blockers"] == []
    assert report["state_write_performed"] is False


def test_blocks_oversell_when_reservation_exceeds_manageable_base(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    state.upsert_position(
        "BTC-USDC",
        {
            "position_size_base": "0.00001",
            "bot_managed_base": "0.00001",
        },
    )
    _seed_open_exit(orders)
    report = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert report["oversell_detected"] is True
    assert "open_d3_exit_reservation_exceeds_manageable_base" in report["blockers"]
