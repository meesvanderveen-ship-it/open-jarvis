from __future__ import annotations

from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d3_full_residual_exit_prep import (
    FUTURE_RESIDUAL_EXIT_ACK,
    build_phase_d3_full_residual_exit_prep_report,
)


class FakeStateStore:
    def __init__(self, position):
        self.position = position

    def get_position(self, ticker):
        if self.position.get("ticker") == ticker:
            return dict(self.position)
        return None


def cfg():
    return SimpleNamespace(
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        phase_d3_exit_order_post_only=True,
        phase_d3_max_exit_order_quote="25.00",
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_new_exit_orders_per_cycle=1,
        phase_c_allowed_tickers=[],
    )


def position():
    return {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "80000",
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0000649067431275",
        "position_size_quote": "4.7952605286012074625",
    }


def test_full_residual_prep_ready_with_live_base_and_rules(tmp_path):
    orders = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")

    report = build_phase_d3_full_residual_exit_prep_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        limit_price="84800.00",
        state_store=FakeStateStore(position()),
        order_store=orders,
        base_increment="0.00000001",
        base_min_size="0.00000001",
        quote_min_size="1",
        price_increment="0.01",
        live_base_available="0.0000649067431275",
    )

    assert report["status"] == "d3_full_residual_exit_final_prep_ready"
    assert report["route"] == "single_full_residual_exit"
    assert report["route_label"] == "TP_CLOSE"
    assert report["rounded_sell_base"] == "0.00006490"
    assert report["base_rounding_delta"] == "6.7431275E-9"
    assert report["estimated_quote_value"] == "5.5035200000"
    assert report["live_base_sufficient"] is True
    assert report["readiness"]["ready"] is True
    assert report["readiness"]["submit_armed"] is False
    assert report["future_live_submit_ack_required"] == FUTURE_RESIDUAL_EXIT_ACK
    assert report["safety_policy"]["does_not_submit"] is True
    assert report["safety_policy"]["does_not_call_coinbase"] is True
    assert "sell_base_rounded_down_to_base_increment" in report["warnings"]


def test_full_residual_prep_blocks_when_open_exit_exists(tmp_path):
    orders = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    orders.upsert_order(
        {
            "client_order_id": "open-d3",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "remaining_size": "0.00001",
            "execution_action": "place_limit_sell",
            "linked_position_id": "pos-1",
            "phase": "D3_controlled_live_reduce_only_exits",
        },
        event_type="test_open_d3",
    )

    report = build_phase_d3_full_residual_exit_prep_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        limit_price="84800.00",
        state_store=FakeStateStore(position()),
        order_store=orders,
        live_base_available="0.0000649067431275",
    )

    assert report["status"] == "d3_full_residual_exit_final_prep_blocked"
    assert "duplicate_open_exit_order_for_position_action" in report["blockers"]
    assert "rounded_sell_base_exceeds_available_after_reservations" in report["blockers"]
    assert report["local_governance"]["open_d3_exit_orders"]["total_open_d3_exit_orders"] == 1
