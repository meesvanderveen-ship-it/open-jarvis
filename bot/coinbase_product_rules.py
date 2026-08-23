from __future__ import annotations

"""Compatibility facade for Coinbase product-rule helpers.

The concrete normalizer lives in :mod:`bot.product_rules`; this module keeps
older compile/test targets importable without introducing another rules source.
"""

from bot.product_rules import (
    PRODUCT_RULE_NORMALIZER_VERSION,
    canonical_product_rules,
    execution_feasibility_context,
    explain_precision_adjustment,
    load_product_rules_cache,
    normalize_base_size,
    normalize_price,
    normalize_product_id,
    normalize_quote_size,
    quote_to_base_size,
    validate_limit_buy_payload,
)

load_coinbase_product_rules_cache = load_product_rules_cache

__all__ = [
    "PRODUCT_RULE_NORMALIZER_VERSION",
    "canonical_product_rules",
    "execution_feasibility_context",
    "explain_precision_adjustment",
    "load_coinbase_product_rules_cache",
    "load_product_rules_cache",
    "normalize_base_size",
    "normalize_price",
    "normalize_product_id",
    "normalize_quote_size",
    "quote_to_base_size",
    "validate_limit_buy_payload",
]
