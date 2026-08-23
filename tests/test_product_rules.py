from __future__ import annotations

from decimal import Decimal

from bot.product_rules import (
    normalize_base_size,
    normalize_price,
    quote_to_base_size,
    validate_limit_buy_payload,
)


RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "base_min_size": "0.00000001",
    "quote_min_size": "1.00",
    "quote_max_size": "100.00",
}


def test_btc_quote_50_converts_to_small_base_not_base_50():
    base = quote_to_base_size("BTC-USDC", "50.00", "65000", RULES)
    assert base == Decimal("0.00076923")
    assert base != Decimal("50")


def test_price_rounds_down_to_price_increment():
    assert normalize_price("BTC-USDC", "65000.123456", RULES) == Decimal("65000.12")


def test_base_size_rounds_down_to_base_increment():
    assert normalize_base_size("BTC-USDC", "0.0007692293", RULES) == Decimal("0.00076922")


def test_min_base_size_is_respected():
    report = validate_limit_buy_payload(
        "BTC-USDC",
        "0.01",
        "65000",
        {**RULES, "base_min_size": "0.001", "quote_min_size": "0.01"},
    )
    assert report["valid"] is False
    assert "base_size_below_product_min_base_size" in report["blockers"]


def test_min_quote_size_is_respected():
    report = validate_limit_buy_payload("BTC-USDC", "0.50", "65000", RULES)
    assert report["valid"] is False
    assert "estimated_quote_below_product_min_quote_size" in report["blockers"]


def test_max_quote_100_is_not_exceeded():
    report = validate_limit_buy_payload("BTC-USDC", "101.00", "65000", RULES, max_quote_size="100.00")
    assert report["valid"] is False
    assert "estimated_quote_above_max_quote_size" in report["blockers"]


def test_missing_product_rules_fail_closed():
    report = validate_limit_buy_payload("BTC-USDC", "50.00", "65000", {})
    assert report["valid"] is False
    assert "product_rules_missing" in report["blockers"]
    assert "price_increment_missing" in report["blockers"]
    assert "base_increment_missing" in report["blockers"]
