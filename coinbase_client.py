"""Compatibility import for the single canonical Coinbase adapter.

Production code must import :class:`bot.coinbase_client.CoinbaseClient`
directly.  This module exists only for older read-only tools while they are
migrated; it deliberately defines no client implementation of its own.
"""

from bot.coinbase_client import CoinbaseClient, normalize_coinbase_account_balances

__all__ = ["CoinbaseClient", "normalize_coinbase_account_balances"]
