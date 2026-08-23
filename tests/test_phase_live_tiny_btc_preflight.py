from types import SimpleNamespace
from decimal import Decimal

from bot.phase_live_tiny_btc_preflight import (
    ACTUAL_SUBMIT_ACK,
    build_btc_usdc_tiny_live_preflight_report,
)


def _cfg(**overrides):
    data = {
        "execution_mode": "live",
        "allowed_tickers": ["BTC-USDC"],
        "phase_c_allowed_tickers": ["BTC-USDC"],
        "default_quote_size_usdc": Decimal("10"),
        "max_notional_usd": Decimal("10"),
        "phase_c_max_order_quote": Decimal("10"),
        "autonomous_max_order_quote": Decimal("10"),
        "max_new_orders_per_cycle": 1,
        "phase_c_max_new_orders_per_cycle": 1,
        "autonomous_max_new_orders_per_cycle": 1,
        "max_open_positions": 1,
        "phase_c_max_open_entry_orders": 1,
        "autonomous_max_open_orders": 1,
        "enable_live_exit_orders": False,
        "enable_phase_d3_actual_exit_submit": False,
        "autonomous_allow_exits": False,
        "phase_c_disable_exit_limit_orders": True,
        "enable_phase_c_actual_coinbase_submit": False,
        "enable_phase_c_live_small_limit_orders": True,
        "enable_live_limit_orders": True,
        "enable_live_entry_orders": True,
        "enable_autonomous_small_live_orderbook_mode": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_tiny_btc_preflight_passes_for_pre_ack_no_submit_scope() -> None:
    report = build_btc_usdc_tiny_live_preflight_report(_cfg(), generated_at="2026-06-08T00:00:00Z")

    assert report["status"] == "pass_btc_usdc_tiny_preflight"
    assert report["blockers"] == []
    assert report["effective_config"]["allowed_tickers"] == ["BTC-USDC"]
    assert "enable_phase_c_actual_coinbase_submit_false_pre_ack" in report["passed_checks"]
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False


def test_tiny_btc_preflight_blocks_multi_ticker_and_oversized_budget() -> None:
    report = build_btc_usdc_tiny_live_preflight_report(
        _cfg(
            allowed_tickers=["BTC-USDC", "ETH-USDC"],
            phase_c_allowed_tickers=["BTC-USDC", "ETH-USDC"],
            default_quote_size_usdc=Decimal("60"),
            max_notional_usd=Decimal("300"),
            phase_c_max_order_quote=Decimal("25"),
            autonomous_max_order_quote=Decimal("25"),
        )
    )

    assert report["status"] == "blocked_btc_usdc_tiny_preflight"
    assert "allowed_tickers_not_btc_usdc_only" in report["blockers"]
    assert "phase_c_allowed_tickers_not_btc_usdc_only" in report["blockers"]
    assert "default_quote_size_usdc_above_10_usdc" in report["blockers"]
    assert "max_notional_usd_above_10_usdc" in report["blockers"]
    assert "phase_c_max_order_quote_above_10_usdc" in report["blockers"]
    assert "autonomous_max_order_quote_above_10_usdc" in report["blockers"]


def test_tiny_btc_preflight_blocks_order_count_and_live_exit_drift() -> None:
    report = build_btc_usdc_tiny_live_preflight_report(
        _cfg(
            max_new_orders_per_cycle=2,
            phase_c_max_new_orders_per_cycle=2,
            autonomous_max_open_orders=4,
            enable_live_exit_orders=True,
            enable_phase_d3_actual_exit_submit=True,
            autonomous_allow_exits=True,
            phase_c_disable_exit_limit_orders=False,
        )
    )

    assert "max_new_orders_per_cycle_not_1" in report["blockers"]
    assert "phase_c_max_new_orders_per_cycle_not_1" in report["blockers"]
    assert "autonomous_max_open_orders_not_1" in report["blockers"]
    assert "enable_live_exit_orders_true" in report["blockers"]
    assert "enable_phase_d3_actual_exit_submit_true" in report["blockers"]
    assert "autonomous_allow_exits_true" in report["blockers"]
    assert "phase_c_disable_exit_limit_orders_false" in report["blockers"]


def test_tiny_btc_preflight_requires_ack_for_actual_submit() -> None:
    no_ack = build_btc_usdc_tiny_live_preflight_report(_cfg(enable_phase_c_actual_coinbase_submit=True))
    with_ack = build_btc_usdc_tiny_live_preflight_report(
        _cfg(enable_phase_c_actual_coinbase_submit=True),
        actual_submit_ack=ACTUAL_SUBMIT_ACK,
        require_actual_submit_enabled=True,
    )

    assert "enable_phase_c_actual_coinbase_submit_true_without_exact_ack" in no_ack["blockers"]
    assert no_ack["status"] == "blocked_btc_usdc_tiny_preflight"
    assert with_ack["status"] == "pass_btc_usdc_tiny_preflight"
    assert "actual_submit_ack_exact" in with_ack["passed_checks"]
    assert "enable_phase_c_actual_coinbase_submit_true_after_ack" in with_ack["passed_checks"]
