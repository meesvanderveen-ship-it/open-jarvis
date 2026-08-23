from __future__ import annotations

from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d3_controlled_live_exits import D3_ACK
from bot.phase_d3_full_residual_exit_prep import FUTURE_RESIDUAL_EXIT_ACK
from bot.phase_d3_full_residual_exit_submit_scaffold import (
    build_phase_d3_full_residual_exit_submit_scaffold_report,
)


class FakeStateStore:
    def __init__(self, position):
        self.position = position

    def get_position(self, ticker):
        if self.position.get("ticker") == ticker:
            return dict(self.position)
        return None


class ExplodingClient:
    def place_limit_order(self, *args, **kwargs):  # pragma: no cover - should never be called in these tests
        raise AssertionError("coinbase write path must not be called")


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


def build_report(tmp_path, **overrides):
    params = {
        "cfg": cfg(),
        "ticker": "BTC-USDC",
        "limit_price": "84800.00",
        "state_store": FakeStateStore(position()),
        "order_store": OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        "base_increment": "0.00000001",
        "base_min_size": "0.00000001",
        "quote_min_size": "1",
        "price_increment": "0.01",
        "live_base_available": "0.0000649067431275",
        "coinbase_client": ExplodingClient(),
    }
    params.update(overrides)
    return build_phase_d3_full_residual_exit_submit_scaffold_report(**params)


def test_default_mode_is_dry_run_and_does_not_submit(tmp_path):
    report = build_report(tmp_path)

    assert report["ready_for_operator_live_ack"] is True
    assert report["live_submit_allowed"] is False
    assert "submit_live_flag_missing" in report["live_gate_blockers"]
    assert report["state_write_performed"] is False
    assert report["coinbase_write_performed"] is False
    assert report["live_order_action_performed"] is False


def test_submit_live_missing_acks_blocks_before_client(tmp_path):
    report = build_report(
        tmp_path,
        submit_live=True,
        confirm_route="single_full_residual_exit",
        confirm_label="TP_CLOSE",
    )

    assert report["live_submit_allowed"] is False
    assert "residual_submit_ack_missing_or_invalid" in report["live_gate_blockers"]
    assert "d3_human_ack_missing_or_invalid" in report["live_gate_blockers"]
    assert report["coinbase_write_performed"] is False
    assert report["live_order_action_performed"] is False


def test_submit_live_missing_submit_flag_blocks_even_with_acks(tmp_path):
    report = build_report(
        tmp_path,
        residual_submit_ack=FUTURE_RESIDUAL_EXIT_ACK,
        d3_human_ack=D3_ACK,
        confirm_route="single_full_residual_exit",
        confirm_label="TP_CLOSE",
    )

    assert report["live_submit_allowed"] is False
    assert "submit_live_flag_missing" in report["live_gate_blockers"]
    assert report["ready_for_operator_live_ack"] is True


def test_stale_tp1_confirmation_is_rejected(tmp_path):
    report = build_report(
        tmp_path,
        confirm_route="single_full_residual_exit",
        confirm_label="TP1",
    )

    assert "stale_tp1_label_rejected" in report["safety_blockers"]
    assert report["ready_for_operator_live_ack"] is False


def test_full_residual_candidate_is_accepted_for_dry_run_review(tmp_path):
    report = build_report(
        tmp_path,
        confirm_route="single_full_residual_exit",
        confirm_label="TP_CLOSE",
    )

    assert report["safety_blockers"] == []
    assert report["prep_report"]["rounded_sell_base"] == "0.00006490"
    assert report["prep_report"]["min_size_checks"]["base_above_min"] is True
    assert report["prep_report"]["min_size_checks"]["quote_above_min"] is True
    assert report["live_submit_allowed"] is False


def test_duplicate_open_exit_blocks(tmp_path):
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

    report = build_report(tmp_path, order_store=orders)

    assert "open_d3_exit_order_exists" in report["safety_blockers"]
    assert "duplicate_exit_order_for_position_action" in report["safety_blockers"]
    assert report["ready_for_operator_live_ack"] is False


def test_oversell_blocks_when_live_base_below_candidate(tmp_path):
    report = build_report(tmp_path, live_base_available="0.00001")

    assert "prep:live_base_available_below_rounded_sell_base" in report["safety_blockers"]
    assert "live_base_not_sufficient" in report["safety_blockers"]
    assert report["ready_for_operator_live_ack"] is False


def test_tiny_quote_blocks_min_quote(tmp_path):
    report = build_report(tmp_path, limit_price="1.00")

    assert "prep:estimated_quote_below_quote_min_size" in report["safety_blockers"]
    assert "quote_min_size_check_failed" in report["safety_blockers"]
    assert report["ready_for_operator_live_ack"] is False
