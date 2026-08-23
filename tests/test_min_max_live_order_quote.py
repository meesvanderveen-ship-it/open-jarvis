from __future__ import annotations

import pytest

from bot.config import BotConfig


def _base_env(monkeypatch, **overrides):
    env = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": "true",
        "PHASE_C43_LIFECYCLE_APPLY_LOCAL": "false",
        "MIN_LIVE_ORDER_QUOTE_USDC": "50.00",
        "MAX_LIVE_ORDER_QUOTE_USDC": "100.00",
        "DEFAULT_QUOTE_SIZE_USDC": "50.00",
        "ENABLE_DYNAMIC_ENTRY_SIZING": "true",
        "MIN_DYNAMIC_ENTRY_QUOTE_USDC": "50.00",
        "MAX_DYNAMIC_ENTRY_QUOTE_USDC": "100.00",
        "MAX_NOTIONAL_USD": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "120.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_OPEN_POSITIONS": "3",
        "MARKET_ORDER_ENABLED": "false",
        "ENABLE_MARKET_ORDERS": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
        "ENABLE_APPROVED_PARAMETER_PROFILE": "false",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_bot_config_accepts_dynamic_min50_max100(monkeypatch):
    _base_env(monkeypatch)
    cfg = BotConfig()
    cfg.validate()
    assert str(cfg.min_live_order_quote_usdc) == "50.00"
    assert str(cfg.max_live_order_quote_usdc) == "100.00"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("MIN_LIVE_ORDER_QUOTE_USDC", "49.99", "MIN_LIVE_ORDER_QUOTE_USDC"),
        ("MAX_LIVE_ORDER_QUOTE_USDC", "100.01", "MAX_LIVE_ORDER_QUOTE_USDC"),
        ("DEFAULT_QUOTE_SIZE_USDC", "10.00", "DEFAULT_QUOTE_SIZE_USDC"),
        ("MAX_NOTIONAL_USD", "101.00", "MAX_NOTIONAL_USD"),
        ("MARKET_ORDER_ENABLED", "true", "MARKET_ORDER_ENABLED"),
    ],
)
def test_full_workflow_live_blocks_invalid_size_or_market_flags(monkeypatch, key, value, message):
    _base_env(monkeypatch, **{key: value})
    with pytest.raises(ValueError, match=message):
        BotConfig().validate()
