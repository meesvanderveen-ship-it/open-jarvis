from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

import run_trader_loop
from bot.phase_live_tiny_btc_preflight import ACTUAL_SUBMIT_ACK


def _satisfy_credential_preflight(monkeypatch) -> None:
    """Geef main() bruikbare credentials zodat de preflight doorlaat.

    Deze tests gaan over de tiny-runtime guard, niet over credentials; zonder
    dit zou de preflight (exit 4) afgaan voordat de guard (exit 2) aan bod
    komt. De credential-preflight zelf wordt gedekt door
    tests/test_credential_setup_flow.py. Sleutel wordt hier gegenereerd.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-guard-tests-0000")
    monkeypatch.setenv(
        "COINBASE_API_KEY",
        "organizations/00000000-0000-0000-0000-000000000000"
        "/apiKeys/11111111-1111-1111-1111-111111111111",
    )
    monkeypatch.setenv("COINBASE_API_SECRET", pem)


def _cfg(**overrides):
    data = {
        "log_level": "INFO",
        "allowed_tickers": ["BTC-USDC"],
        "phase_c_allowed_tickers": ["BTC-USDC"],
        "execution_mode": "live",
        "primary_interval_hours": 4,
        "default_quote_size_usdc": Decimal("10"),
        "max_notional_usd": Decimal("10"),
        "phase_c_max_order_quote": Decimal("10"),
    }
    data.update(overrides)
    cfg = SimpleNamespace(**data)
    cfg.validate = lambda: None
    return cfg


def test_runtime_startup_guard_passes_btc_only_wrapper(monkeypatch) -> None:
    monkeypatch.setenv("BTC_USDC_TINY_WRAPPER_MODE", "true")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")

    diagnostic = run_trader_loop._enforce_tiny_runtime_startup_guard(_cfg())

    assert diagnostic["tiny_mode_active"] is True
    assert diagnostic["effective_runtime_tickers"] == ["BTC-USDC"]
    assert diagnostic["phase_c_allowed_tickers"] == ["BTC-USDC"]
    assert diagnostic["fail_closed"] is False
    assert diagnostic["no_llm_call"] is True
    assert diagnostic["no_coinbase_call"] is True
    assert diagnostic["state_write_performed"] is False


def test_tiny_ack_non_btc_tickers_hard_fails_before_engine_cycle_or_state(monkeypatch, tmp_path) -> None:
    _satisfy_credential_preflight(monkeypatch)
    calls = {"engine": 0, "cycle": 0, "publisher": 0}
    state_file = tmp_path / "positions.json"
    before = state_file.read_bytes() if state_file.exists() else b""

    class Engine:
        def __init__(self):
            calls["engine"] += 1

        def run_cycle(self):
            calls["cycle"] += 1
            return {"results": []}

    monkeypatch.setenv("BTC_USDC_TINY_ACTUAL_SUBMIT_ACK", ACTUAL_SUBMIT_ACK)
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC,ETH-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setattr(run_trader_loop, "BotConfig", lambda: _cfg(allowed_tickers=["BTC-USDC", "ETH-USDC"]))
    monkeypatch.setattr(run_trader_loop, "StrategyEngine", Engine)
    monkeypatch.setattr(run_trader_loop, "_init_replica_publisher", lambda: calls.__setitem__("publisher", calls["publisher"] + 1))

    with pytest.raises(SystemExit) as exc:
        run_trader_loop.main()

    assert exc.value.code == 2
    assert calls == {"engine": 0, "cycle": 0, "publisher": 0}
    assert (state_file.read_bytes() if state_file.exists() else b"") == before


def test_startup_diagnostic_mode_prints_btc_only_scope_without_engine(monkeypatch, capsys) -> None:
    calls = {"engine": 0}

    class Engine:
        def __init__(self):
            calls["engine"] += 1

    monkeypatch.setenv("BTC_USDC_TINY_WRAPPER_MODE", "true")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setattr(run_trader_loop, "BotConfig", lambda: _cfg())
    monkeypatch.setattr(run_trader_loop, "StrategyEngine", Engine)
    monkeypatch.setattr(run_trader_loop.sys, "argv", ["run_trader_loop.py", "--startup-diagnostic"])

    run_trader_loop.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["effective_runtime_tickers"] == ["BTC-USDC"]
    assert payload["ticker_source"] == "env:ALLOWED_TICKERS -> BotConfig.allowed_tickers"
    assert payload["tiny_mode_active"] is True
    assert payload["ack_present"] is False
    assert payload["fail_closed"] is False
    assert calls["engine"] == 0
