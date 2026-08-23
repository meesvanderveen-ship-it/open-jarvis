from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_c44_poll_to_apply_closeout import build_phase_c44_poll_to_apply_closeout_report


def _cfg(tmp_path: Path, **overrides):
    base = dict(
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
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
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


def _add_order(store: OrderStore):
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-closeout-test",
        "exchange_order_id": "cb-closeout-1",
        "order_id": "cb-closeout-1",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
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


def _snap(status="CANCELLED", **extra):
    data = {
        "client_order_id": "phasec-BTCUSDC-closeout-test",
        "order_id": "cb-closeout-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": status,
    }
    data.update(extra)
    return data


def test_preview_cancelled_snapshot_is_read_only(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("CANCELLED")],
    )
    assert report["status"] == "closeout_preview_ready"
    assert report["governance_report"]["status"] == "poll_only_governed"
    assert report["preview_report"]["proposed_actions"][0]["action"] == "mark_cancelled"
    assert report["apply_report"] is None
    assert store.get_order("phasec-BTCUSDC-closeout-test")["status"] == "submitted"


def test_apply_cancelled_snapshot_requires_governance_and_closes_local_order(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("CANCELLED")],
        apply_local=True,
    )
    assert report["status"] == "closeout_apply_local_completed"
    assert report["governance_report"]["status"] == "apply_local_governed"
    assert report["apply_report"]["applied_actions"][0]["action"] == "mark_cancelled"
    order = store.get_order("phasec-BTCUSDC-closeout-test")
    assert order["status"] == "cancelled"
    assert order["remaining_quote"] == "0"
    assert report["local_open_c43_after"] == 0


def test_open_snapshot_keeps_order_open_and_does_not_apply(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        live_orders_snapshot=[_snap("OPEN")],
        apply_local=True,
    )
    assert report["status"] == "open_order_kept_open_no_apply_needed"
    assert report["preview_report"]["proposed_actions"][0]["action"] == "kept_open"
    assert report["apply_report"] is None
    assert store.get_order("phasec-BTCUSDC-closeout-test")["status"] == "submitted"


def test_filled_snapshot_blocks_apply_without_explicit_fill_ack(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    state = FakeStateStore()
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
        apply_local=True,
        build_d2_plan=True,
        build_d3_preview=True,
    )
    assert report["status"] == "blocked_review_required"
    assert "fill_or_partial_fill_detected_requires_allow_fill_apply" in report["blockers"]
    assert report["apply_report"] is None
    assert state.get_position("BTC-USDC") is None
    assert store.get_order("phasec-BTCUSDC-closeout-test")["status"] == "submitted"


def test_filled_snapshot_with_fill_ack_can_build_d2_d3_preview_without_live_sell(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    state = FakeStateStore()
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=state,
        live_orders_snapshot=[_snap("FILLED", filled_size="0.00013333", average_filled_price="75000")],
        apply_local=True,
        allow_fill_apply=True,
        build_d2_plan=True,
        build_d3_preview=True,
    )
    assert report["status"] == "closeout_apply_local_completed"
    assert store.get_order("phasec-BTCUSDC-closeout-test")["status"] == "filled"
    assert state.get_position("BTC-USDC") is not None
    assert report["apply_report"]["d2_reports"]
    assert report["apply_report"]["d3_previews"]
    assert report["apply_report"]["d3_previews"][0]["live_submission_attempted"] is False
    assert report["safety_policy"]["never_submits_live_sell_orders"] is True

class FakeCoinbaseClient:
    def __init__(self, raw_order):
        self.raw_order = raw_order
        self.get_order_calls = []

    def get_order(self, order_id):
        self.get_order_calls.append(order_id)
        return {"order": dict(self.raw_order)}

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


def test_apply_after_coinbase_poll_reuses_preview_snapshot_and_closes_local_order(tmp_path: Path):
    store = _store(tmp_path)
    _add_order(store)
    client = FakeCoinbaseClient({
        "order_id": "cb-closeout-1",
        "client_order_id": "phasec-BTCUSDC-closeout-test",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "CANCELLED",
        "filled_size": "0",
        "average_filled_price": "0",
    })
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=_cfg(tmp_path),
        ticker="BTC-USDC",
        order_store=store,
        state_store=FakeStateStore(),
        coinbase_client=client,
        allow_coinbase_poll=True,
        apply_local=True,
    )
    assert report["preview_report"]["coinbase_call_attempted"] is True
    assert report["preview_report"]["proposed_actions"][0]["action"] == "mark_cancelled"
    assert report["status"] == "closeout_apply_local_completed"
    assert report["apply_report"]["coinbase_call_attempted"] is False
    assert report["apply_report"]["applied_actions"][0]["action"] == "mark_cancelled"
    assert report["local_open_c43_after"] == 0
    assert store.get_order("phasec-BTCUSDC-closeout-test")["status"] == "cancelled"
