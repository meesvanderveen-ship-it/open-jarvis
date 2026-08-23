from __future__ import annotations

import importlib

import replication.config


def test_replication_config_respects_bot_config_skip_dotenv(monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")

    importlib.reload(replication.config)

    assert replication.config.os.getenv("ALLOWED_TICKERS") == "BTC-USDC"
    assert replication.config.os.getenv("PHASE_C_ALLOWED_TICKERS") == "BTC-USDC"
