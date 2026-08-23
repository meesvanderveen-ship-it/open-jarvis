from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.atomic_io import process_lock
from bot.order_store import OrderStore
from bot.phase_c43_lifecycle_orchestrator import build_phase_c43_lifecycle_orchestrator_report


def _cfg(**overrides):
    base = dict(
        enable_phase_d2_position_executor=True,
        phase_d2_min_expected_net_edge_pct="0.0010",
        phase_d2_min_reward_to_fee_ratio="1.0",
        phase_d2_min_reward_to_risk_ratio="0.5",
        phase_d2_estimated_entry_fee_pct="0.0010",
        phase_d2_estimated_exit_fee_pct="0.0010",
        phase_d2_estimated_spread_slippage_pct="0.0010",
        phase_d2_fee_safety_buffer_pct="0.0010",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        phase_d3_max_exit_order_quote="25.00",
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_new_exit_orders_per_cycle=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeStateStore:
    def __init__(self):
        self.positions = {}

    def get_position(self, ticker):
        return self.positions.get(str(ticker).upper())

    def get_positions(self):
        return dict(self.positions)

    def create_position(self, *, ticker, side, order_id, entry_price, position_size_base, position_size_quote, entry_reason="", extra=None):
        payload = {
            "ticker": str(ticker).upper(),
            "status": "open",
            "last_side": side,
            "order_id": order_id,
            "entry_price": entry_price,
            "position_size_base": position_size_base,
            "position_size_quote": position_size_quote,
            "entry_reason": entry_reason,
            "bot_managed_base": position_size_base,
            "stop_price": "49000",
        }
        if extra:
            payload.update(extra)
        self.positions[str(ticker).upper()] = payload
        return payload


def _store_with_order(tmp_path: Path, **overrides):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    order = {
        "client_order_id": "phasec-BTCUSDC-test",
        "exchange_order_id": "cb-order-1",
        "order_id": "cb-order-1",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "opened_via_phase_c43": True,
        "execution_action": "place_limit_buy",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "remaining_quote": "25.00",
        "remaining_size": "0.0005",
        "limit_price": "50000",
    }
    order.update(overrides)
    store.upsert_order(order)
    return store


def test_preview_cancelled_order_does_not_modify_store(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{"client_order_id": "phasec-BTCUSDC-test", "order_id": "cb-order-1", "product_id": "BTC-USDC", "side": "BUY", "status": "CANCELLED"}],
    )
    assert report["status"] == "preview_completed"
    assert report["proposed_actions"][0]["action"] == "mark_cancelled"
    assert report["proposed_actions"][0]["writes_local_state"] is True
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "submitted"
    assert not (tmp_path / "runtime_mutation.lock").exists()


def test_apply_cancelled_order_marks_local_final_without_position(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{"client_order_id": "phasec-BTCUSDC-test", "order_id": "cb-order-1", "product_id": "BTC-USDC", "side": "BUY", "status": "CANCELLED"}],
        apply_local=True,
    )
    order = store.get_order("phasec-BTCUSDC-test")
    assert report["status"] == "apply_local_completed"
    assert report["mutation_lock"] == {"acquired": True, "reentrant": False}
    assert report["applied_actions"][0]["action"] == "mark_cancelled"
    assert order["status"] == "cancelled"
    assert order["position_created"] is False
    assert state.get_position("BTC-USDC") is None


def test_apply_reenters_the_runner_mutation_lock(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / "runtime_mutation.lock"
    monkeypatch.setenv("RUN_TRADER_LOOP_LOCK_PATH", str(lock_path))
    store = _store_with_order(tmp_path)
    state = FakeStateStore()

    with process_lock(lock_path):
        report = build_phase_c43_lifecycle_orchestrator_report(
            cfg=_cfg(),
            ticker="BTC-USDC",
            order_store=store,
            state_store=state,
            live_orders_snapshot=[{
                "client_order_id": "phasec-BTCUSDC-test",
                "order_id": "cb-order-1",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "status": "CANCELLED",
            }],
            apply_local=True,
        )

    assert report["mutation_lock"] == {"acquired": True, "reentrant": True}
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "cancelled"


def test_apply_filled_order_creates_position_d2_plan_and_d3_preview_without_sell_submit(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0005",
            "average_filled_price": "50000",
        }],
        apply_local=True,
        build_d2_plan=True,
        build_d3_preview=True,
    )
    order = store.get_order("phasec-BTCUSDC-test")
    assert order["status"] == "filled"
    assert state.get_position("BTC-USDC") is not None
    assert report["d2_reports"]
    assert report["d3_previews"]
    assert order["d2_plan_created"] is True
    assert order["d2_plan_status"] == report["d2_reports"][0]["status"]
    assert order["d2_plan_id"] == report["d2_reports"][0]["plan"]["plan_id"]
    assert order["d2_plan_persisted"] is False
    assert order["d2_plan_persisted_ticker_key"] == "BTC-USDC"
    assert order["d3_preview_created"] is True
    assert order["d3_preview_status"] == report["d3_previews"][0]["status"]
    if "selected_exit_intent" in report["d3_previews"][0]:
        assert order["d3_preview_label"] == report["d3_previews"][0]["selected_exit_intent"]["label"]
        assert order["d3_preview_intent_id"] == report["d3_previews"][0]["selected_exit_intent"]["intent_id"]
    assert report["d3_previews"][0]["live_submission_attempted"] is False
    assert report["d3_previews"][0]["live_order_submitted"] is False
    assert report["safety_policy"]["does_not_create_live_exit_orders"] is True
    assert report["mutation_lock"] == {"acquired": True, "reentrant": False}
    assert report["c43_reconcile_report"]["mutation_lock"] == {"acquired": True, "reentrant": True}


def test_apply_filled_order_without_d2_or_d3_build_keeps_default_order_metadata(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0005",
            "average_filled_price": "50000",
        }],
        apply_local=True,
    )
    order = store.get_order("phasec-BTCUSDC-test")
    assert report["d2_reports"] == []
    assert report["d3_previews"] == []
    assert order["d2_plan_created"] is False
    assert order["d3_preview_created"] is False
    assert "d2_plan_status" not in order
    assert "d3_preview_status" not in order


class FakeCoinbaseClient:
    def get_order(self, order_id):
        assert order_id == "cb-order-1"
        return {"order": {"order_id": order_id, "product_id": "BTC-USDC", "side": "BUY", "status": "OPEN"}}

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


def test_allow_coinbase_poll_uses_read_only_client_and_keeps_open(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        coinbase_client=FakeCoinbaseClient(),
        allow_coinbase_poll=True,
    )
    assert report["coinbase_call_attempted"] is True
    assert report["coinbase_call_succeeded"] is True
    assert report["proposed_actions"][0]["action"] == "kept_open"
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "submitted"


@pytest.mark.parametrize("exchange_status", ["ACTIVE", "NEW", "QUEUED", "UNKNOWN", ""])
def test_nonterminal_exchange_status_never_releases_c43_entry_reservation(tmp_path: Path, exchange_status: str):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": exchange_status,
        }],
        apply_local=True,
    )

    assert report["proposed_actions"][0]["action"] == "kept_open"
    assert [action["action"] for action in report["applied_actions"]] == ["kept_open"]
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "submitted"
    assert state.get_position("BTC-USDC") is None


def test_open_entry_snapshot_cannot_trigger_d2_or_d3_handoff(tmp_path: Path):
    store = _store_with_order(tmp_path)
    state = FakeStateStore()
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "OPEN",
        }],
        apply_local=True,
        build_d2_plan=True,
        build_d3_preview=True,
    )

    assert report["d2_reports"] == []
    assert report["d3_previews"] == []
    assert state.get_position("BTC-USDC") is None
