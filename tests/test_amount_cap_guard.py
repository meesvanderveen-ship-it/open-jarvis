from __future__ import annotations

from types import SimpleNamespace

from bot.amount_cap_guard import evaluate_amount_cap_guard


BTC_RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}

ADA_RULES = {
    "product_id": "ADA-USDC",
    "price_increment": "0.0001",
    "base_increment": "0.00000001",
    "quote_increment": "0.0001",
    "quote_min_size": "1.00",
}


def _cfg(**overrides):
    base = {
        "phase_c_max_order_quote": "100.00",
        "autonomous_max_order_quote": "100.00",
        "max_notional_usd": "100.00",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_amount_cap_quote_50_does_not_become_base_50():
    report = evaluate_amount_cap_guard(
        cfg=_cfg(),
        ticker="BTC-USDC",
        requested_quote="50.00",
        limit_price="65000.00",
        product_rules=BTC_RULES,
    )

    assert report["accepted"] is True
    assert report["normalized_quote_size"] == "50.00"
    assert report["normalized_base_size"] != "50.00"
    assert "quote_to_base_conversion_present" in report["passed_checks"]


def test_amount_cap_requested_quote_above_100_blocks():
    report = evaluate_amount_cap_guard(
        cfg=_cfg(),
        ticker="BTC-USDC",
        requested_quote="100.01",
        limit_price="65000.00",
        product_rules=BTC_RULES,
    )

    assert report["accepted"] is False
    assert "requested_quote_above_phase_c_max_order_quote" in report["blockers"]
    assert "requested_quote_above_autonomous_max_order_quote" in report["blockers"]
    assert "requested_quote_above_max_notional_usd" in report["blockers"]


def test_amount_cap_low_price_asset_base_can_exceed_quote_numerically():
    report = evaluate_amount_cap_guard(
        cfg=_cfg(),
        ticker="ADA-USDC",
        requested_quote="20.00",
        limit_price="0.1645",
        product_rules=ADA_RULES,
    )

    assert report["accepted"] is True
    assert float(report["normalized_base_size"]) > 20
    assert report["safety_policy"]["low_price_assets_may_have_base_numerically_above_quote"] is True
