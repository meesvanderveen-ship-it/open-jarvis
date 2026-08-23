from __future__ import annotations

from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d31_lifecycle_readiness import (
    D31_ENTRY_ARM_ACK,
    D31_READY_ENTRY_ARMING,
    assess_phase_d31_entry_pilot_readiness,
    build_phase_d31_lifecycle_readiness_report,
)


def _cfg(**overrides):
    base = dict(
        allowed_tickers=["BTC-USDC", "ETH-USDC", "SUI-USDC"],
        phase_c_allowed_tickers=["BTC-USDC", "ETH-USDC"],
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c_actual_coinbase_submit=False,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        autonomous_entry_only_first=True,
        autonomous_require_post_only=True,
        phase_c_disable_exit_limit_orders=True,
        phase_c_max_order_quote="25.00",
        autonomous_max_order_quote="25.00",
        phase_c_max_open_entry_orders=4,
        autonomous_max_open_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_new_orders_per_cycle=1,
        enable_phase_d2_position_executor=True,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_exit_order_quote="25.00",
        phase_d3_max_new_exit_orders_per_cycle=1,
        phase_d3_exit_order_post_only=True,
        phase_d3_require_reduce_only_local=True,
        phase_d2_min_expected_net_edge_pct="0.0125",
        phase_d2_min_reward_to_fee_ratio="3.0",
        phase_d2_min_reward_to_risk_ratio="1.5",
        phase_d2_estimated_entry_fee_pct="0.0040",
        phase_d2_estimated_exit_fee_pct="0.0040",
        phase_d2_estimated_spread_slippage_pct="0.0020",
        phase_d2_fee_safety_buffer_pct="0.0025",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_phase_d1_exit_orderbook_scaffold=True,
        enable_phase_d1_actual_exit_submit=False,
        phase_d1_max_exit_order_quote="25.00",
        phase_d1_max_open_exit_orders=4,
        phase_d1_require_reduce_only=True,
        phase_d1_exit_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _EmptyState:
    def get_position(self, ticker):
        return None
    def get_positions(self):
        return {}


class _RealPositionState:
    def get_position(self, ticker):
        return self.get_positions().get(ticker)
    def get_positions(self):
        return {
            "BTC-USDC": {
                "ticker": "BTC-USDC",
                "status": "open",
                "order_id": "pos-1",
                "entry_price": "100.00",
                "position_size_base": "0.25",
                "bot_managed_base": "0.25",
                "position_size_quote": "25.00",
                "stop_price": "97.50",
            }
        }


def test_d31_ready_for_entry_only_arming_when_stack_safe(tmp_path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = assess_phase_d31_entry_pilot_readiness(cfg=_cfg(), ticker="BTC-USDC", order_store=store, state_store=_EmptyState())
    assert report["status"] == D31_READY_ENTRY_ARMING
    assert report["ready_for_controlled_entry_only_arming"] is True
    assert report["config_flags"]["enable_live_exit_orders"] is False
    assert report["config_flags"]["phase_c_disable_exit_limit_orders"] is True
    assert "entry_actual_submit_currently_false_preview_safe" in report["passed_checks"]


def test_d31_blocks_if_live_exits_are_enabled_before_position(tmp_path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = assess_phase_d31_entry_pilot_readiness(cfg=_cfg(enable_live_exit_orders=True), ticker="BTC-USDC", order_store=store, state_store=_EmptyState())
    assert report["ready_for_controlled_entry_only_arming"] is False
    assert "live_exit_orders_enabled_before_position" in report["blockers"]


def test_d31_blocks_if_selected_ticker_already_has_position(tmp_path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = assess_phase_d31_entry_pilot_readiness(cfg=_cfg(), ticker="BTC-USDC", order_store=store, state_store=_RealPositionState())
    assert report["ready_for_controlled_entry_only_arming"] is False
    assert "selected_ticker_already_has_manageable_position" in report["blockers"]


def test_d31_require_actual_submit_requires_ack_and_flag(tmp_path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = assess_phase_d31_entry_pilot_readiness(cfg=_cfg(), ticker="BTC-USDC", order_store=store, state_store=_EmptyState(), require_actual_entry_submit=True)
    assert "entry_actual_submit_disabled" in report["blockers"]
    assert "human_ack_missing_or_invalid" in report["blockers"]

    armed = assess_phase_d31_entry_pilot_readiness(cfg=_cfg(enable_phase_c_actual_coinbase_submit=True), ticker="BTC-USDC", order_store=store, state_store=_EmptyState(), require_actual_entry_submit=True, human_ack=D31_ENTRY_ARM_ACK)
    assert "human_ack_matches_d31" in armed["passed_checks"]
    assert "entry_actual_submit_enabled" in armed["passed_checks"]


def test_d31_full_report_aggregates_c43_d2_d3_without_submit(tmp_path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = build_phase_d31_lifecycle_readiness_report(cfg=_cfg(), ticker="BTC-USDC", order_store=store, state_store=_EmptyState())
    assert report["ready_for_controlled_entry_only_arming"] is True
    assert report["stack"]["c43_open_entry_orders"] == 0
    assert report["stack"]["d2_plan_present"] is False
    assert report["stack"]["d3_position_present"] is False
    assert report["safety_policy"]["does_not_submit_orders"] is True
