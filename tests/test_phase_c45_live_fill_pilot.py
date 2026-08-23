from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_c45_live_fill_pilot import (
    C45_FILL_APPLY_ACK,
    build_phase_c45_live_fill_pilot_report,
)


def _cfg(tmp_path: Path, **overrides):
    base = dict(
        replication_enabled=False,
        enable_phase_c_actual_coinbase_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        enable_phase_c43_lifecycle_orchestrator=True,
        phase_c43_lifecycle_allow_coinbase_poll=False,
        phase_c43_lifecycle_apply_local=False,
        phase_c43_lifecycle_build_d2_plan=False,
        phase_c43_lifecycle_persist_d2_plan=False,
        phase_c43_lifecycle_build_d3_preview=False,
        phase_c43_lifecycle_max_poll_orders_per_cycle=4,
        phase_c43_lifecycle_max_apply_actions_per_cycle=4,
        phase_c43_lifecycle_apply_requires_coinbase_poll=True,
        phase_c43_lifecycle_block_apply_when_live_exits_enabled=True,
        phase_c43_lifecycle_order_store_path=str(tmp_path / "orders.json"),
        phase_c43_lifecycle_order_events_path=str(tmp_path / "events.jsonl"),
        order_store_max_records=200,
        phase_c_max_order_quote="25.00",
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
        pos = {
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
            pos.update(extra)
        self.positions[str(ticker).upper()] = pos
        return pos


def _store(tmp_path: Path):
    return OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")


def _add_order(store: OrderStore, *, cid="phasec-BTCUSDC-fill-test", oid="cb-fill-1", status="submitted"):
    store.upsert_order({
        "client_order_id": cid,
        "exchange_order_id": oid,
        "order_id": oid,
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": status,
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "opened_via_phase_c43": True,
        "execution_action": "place_limit_buy",
        "size_quote": "10.00",
        "size_base": "0.00013333",
        "remaining_quote": "10.00",
        "remaining_size": "0.00013333",
        "limit_price": "75000",
    })


def _snap(status="OPEN", **extra):
    data = {
        "client_order_id": "phasec-BTCUSDC-fill-test",
        "order_id": "cb-fill-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": status,
    }
    data.update(extra)
    return data


def test_no_open_order_is_safe_noop(tmp_path: Path):
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=_store(tmp_path),
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
    )
    assert report["status"] == "no_open_c43_order_noop"
    assert report["local_open_c43_before"] == 0
    assert report["local_open_c43_after"] == 0
    assert report["safety_policy"]["never_submits_live_sell_orders"] is True


def test_open_order_waits_for_fill_without_mutation(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("OPEN")],
        apply_fill=True,
        fill_apply_ack=C45_FILL_APPLY_ACK,
    )
    assert report["status"] == "fill_pilot_waiting_for_fill"
    assert report["c44_report"]["preview_report"]["proposed_actions"][0]["action"] == "kept_open"
    assert store.get_order("phasec-BTCUSDC-fill-test")["status"] == "submitted"
    assert report["local_open_c43_after"] == 1


def test_fill_detected_requires_c45_ack_and_does_not_apply(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    state = FakeStateStore()
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
    )
    assert report["status"] == "blocked_review_required"
    assert "fill_or_partial_fill_detected_requires_c45_apply_fill_ack" in report["blockers"]
    assert store.get_order("phasec-BTCUSDC-fill-test")["status"] == "submitted"
    assert state.get_position("BTC-USDC") is None


def test_fill_apply_builds_position_d2_and_d3_preview_without_live_sell(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    state = FakeStateStore()
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
        apply_fill=True,
        fill_apply_ack=C45_FILL_APPLY_ACK,
        build_d2_plan=True,
        build_d3_preview=True,
    )
    assert report["status"] == "fill_apply_local_completed"
    order = store.get_order("phasec-BTCUSDC-fill-test")
    assert order["status"] == "filled"
    assert state.get_position("BTC-USDC") is not None
    assert report["fill_apply_summary"]["d2_reports_count"] == 1
    assert report["fill_apply_summary"]["d3_previews_count"] == 1
    assert order["d2_plan_created"] is True
    assert order["d2_plan_status"] == report["c44_report"]["apply_report"]["d2_reports"][0]["status"]
    assert order["d2_plan_id"] == report["c44_report"]["apply_report"]["d2_reports"][0]["plan"]["plan_id"]
    assert order["d2_plan_persisted"] is False
    assert order["d3_preview_created"] is True
    assert order["d3_preview_status"] == report["c44_report"]["apply_report"]["d3_previews"][0]["status"]
    d3 = report["c44_report"]["apply_report"]["d3_previews"][0]
    if "selected_exit_intent" in d3:
        assert order["d3_preview_label"] == d3["selected_exit_intent"]["label"]
        assert order["d3_preview_intent_id"] == d3["selected_exit_intent"]["intent_id"]
    assert d3["live_submission_attempted"] is False
    assert d3["live_order_submitted"] is False
    assert report["safety_policy"]["never_submits_live_sell_orders"] is True


def test_non_fill_final_status_is_routed_back_to_c44_closeout(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("CANCELLED")],
    )
    assert report["status"] == "non_fill_closeout_detected_use_c44"
    assert "non_fill_final_status_detected_use_c44_closeout_route" in report["warnings"]
    assert store.get_order("phasec-BTCUSDC-fill-test")["status"] == "submitted"


def test_safety_blocks_when_live_exits_are_enabled(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c45_live_fill_pilot_report(
        cfg=_cfg(tmp_path, enable_live_exit_orders=True),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
        apply_fill=True,
        fill_apply_ack=C45_FILL_APPLY_ACK,
    )
    assert report["status"] == "blocked_review_required"
    assert "live_exit_orders_enabled_forbidden" in report["blockers"]
    assert store.get_order("phasec-BTCUSDC-fill-test")["status"] == "submitted"
