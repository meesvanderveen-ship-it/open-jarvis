from __future__ import annotations

from decimal import Decimal

from bot.coinbase_client import CoinbaseClient


def _client_with_accounts(accounts: list[dict]) -> CoinbaseClient:
    client = CoinbaseClient()
    client.get_accounts = lambda: {"accounts": accounts}  # type: ignore[method-assign]
    return client


def test_sums_available_and_hold_per_currency():
    client = _client_with_accounts(
        [
            {"currency": "USDC", "available_balance": {"value": "500.00"}, "hold": {"value": "0"}},
            {"currency": "SOL", "available_balance": {"value": "9.5"}, "hold": {"value": "0.5"}},
        ]
    )

    balances = client.get_all_balances()

    assert balances["USDC"] == Decimal("500.00")
    assert balances["SOL"] == Decimal("10.0")


def test_zero_balance_accounts_are_omitted():
    client = _client_with_accounts(
        [
            {"currency": "USDC", "available_balance": {"value": "0"}, "hold": {"value": "0"}},
            {"currency": "ADA", "available_balance": {"value": "12.0"}, "hold": {"value": "0"}},
        ]
    )

    balances = client.get_all_balances()

    assert "USDC" not in balances
    assert balances["ADA"] == Decimal("12.0")


def test_duplicate_currency_accounts_are_combined():
    # Coinbase can return more than one account per currency (e.g. a legacy
    # and a retail-portfolio account) -- both must count toward the total.
    client = _client_with_accounts(
        [
            {"currency": "USDC", "available_balance": {"value": "300.00"}, "hold": {"value": "0"}},
            {"currency": "USDC", "available_balance": {"value": "200.00"}, "hold": {"value": "0"}},
        ]
    )

    balances = client.get_all_balances()

    assert balances["USDC"] == Decimal("500.00")
