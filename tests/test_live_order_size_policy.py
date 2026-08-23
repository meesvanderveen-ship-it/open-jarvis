from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.live_order_size_policy import validate_entry_quote_size, validate_exit_quote_size
from bot.phase_c_live_submitter import build_phase_c_live_entry_payload


def _cfg(**overrides):
    base = dict(
        min_live_order_quote_usdc=Decimal("50.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        phase_d3_max_exit_order_quote=Decimal("120.00"),
        controlled_stop_exit_max_quote_usd=Decimal("120.00"),
        phase_c_live_order_post_only=True,
        phase_c_disable_exit_limit_orders=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_entry_quote_policy_blocks_under_min_and_above_max():
    cfg = _cfg()
    for quote in ["5", "10", "49.99"]:
        result = validate_entry_quote_size(quote, cfg)
        assert result["accepted"] is False
        assert "quote_size_below_min_live_order_quote" in result["blockers"]

    for quote in ["50", "75", "100"]:
        assert validate_entry_quote_size(quote, cfg)["accepted"] is True

    result = validate_entry_quote_size("100.01", cfg)
    assert result["accepted"] is False
    assert "quote_size_above_max_live_order_quote" in result["blockers"]


def test_submitter_blocks_under_bot_min_even_when_product_min_is_lower():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_intent={"side": "BUY", "execution_action": "place_limit_buy", "size_quote": "10", "limit_price": "100"},
        guard_result={"guard_allows_live_submit": True},
        product_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
    )
    assert payload["accepted"] is False
    assert "quote_size_below_min_live_order_quote" in payload["reject_reasons"]


def test_submitter_blocks_when_precision_rounding_would_drop_below_50():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="LOW-USDC",
        order_intent={"side": "BUY", "execution_action": "place_limit_buy", "size_quote": "50.00", "limit_price": "3.00"},
        guard_result={"guard_allows_live_submit": True},
        product_rules={"quote_min_size": "1", "base_increment": "1", "price_increment": "0.01", "quote_increment": "0.01"},
    )
    assert payload["accepted"] is False
    assert "normalized_quote:quote_size_below_min_live_order_quote" in payload["reject_reasons"]


def test_partial_exit_under_min_blocks_but_full_close_is_allowed():
    partial = validate_exit_quote_size(estimated_quote="49.99", cfg=_cfg(), label="TP1", is_full_close=False)
    assert partial["accepted"] is False
    assert "exit_quote_below_min_live_order_quote" in partial["blockers"]

    full_close = validate_exit_quote_size(estimated_quote="49.99", cfg=_cfg(), label="TP_CLOSE", is_full_close=True)
    assert full_close["accepted"] is True
    assert "full_close_below_min_live_order_quote_allowed" in full_close["warnings"]


def test_d3_and_controlled_stop_exit_have_separate_120_usdc_capacity():
    assert validate_exit_quote_size(estimated_quote="120.00", cfg=_cfg(), label="TP_CLOSE", is_full_close=True)["accepted"] is True
    assert validate_exit_quote_size(estimated_quote="120.00", cfg=_cfg(), label="CONTROLLED_STOP_EXIT", is_full_close=True)["accepted"] is True
