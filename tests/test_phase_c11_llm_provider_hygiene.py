from __future__ import annotations

import json
import sys
import types
from pathlib import Path

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    class _OpenAI:
        def __init__(self, *args, **kwargs):
            pass
    openai_stub.OpenAI = _OpenAI
    sys.modules["openai"] = openai_stub

if "anthropic" not in sys.modules:
    anthropic_stub = types.ModuleType("anthropic")
    class _Anthropic:
        def __init__(self, *args, **kwargs):
            pass
    anthropic_stub.Anthropic = _Anthropic
    sys.modules["anthropic"] = anthropic_stub

from bot.config import BotConfig
from bot.llm_clients import (
    _provider_error_type,
    _truncate_text,
    _write_llm_corrupt_log,
    _write_llm_provider_error_log,
)
from bot.strategy_engine import StrategyEngine
from tools.show_llm_provider_health import build_llm_provider_health


def test_deepseek_and_anthropic_are_explicitly_disabled_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_DEEPSEEK_PREPROCESS", raising=False)
    monkeypatch.delenv("ENABLE_ANTHROPIC_FALLBACK", raising=False)

    cfg = BotConfig()
    assert cfg.enable_deepseek_preprocess is False
    assert cfg.enable_anthropic_fallback is False
    cfg.validate()


def test_provider_error_classification_keeps_billing_out_of_corrupt_log():
    assert _provider_error_type("Your credit balance is too low to access the Anthropic API") == "provider_billing_or_credit_error"
    assert _provider_error_type("overloaded_error") == "provider_unavailable_or_overloaded"
    assert _provider_error_type("Connection error.") == "provider_network_or_connection_error"
    assert _provider_error_type("[Errno -3] Temporary failure in name resolution") == "provider_network_or_connection_error"
    assert _provider_error_type("invalid api key") == "provider_auth_error"
    assert _provider_error_type("model_not_found") == "provider_model_error"
    assert _provider_error_type("no_valid_json_object_found") is None


def test_llm_log_truncation_and_provider_health_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = type("Cfg", (), {
        "llm_corrupt_logging_enabled": True,
        "llm_provider_error_logging_enabled": True,
        "llm_corrupt_max_raw_chars": 80,
    })()

    _write_llm_corrupt_log("openai", "gpt", "BTC-USDC", "entry_gate", "x" * 500, "no_valid_json_object_found", cfg)
    _write_llm_provider_error_log("anthropic", "claude", "BTC-USDC", "judge", "credit balance is too low", "provider_billing_or_credit_error", cfg)

    corrupt_row = json.loads(Path("logs/llm_corrupt.jsonl").read_text().splitlines()[0])
    assert corrupt_row["raw_text_truncated"] is True
    assert corrupt_row["raw_text_original_chars"] == 500

    report = build_llm_provider_health(tmp_path, sample=10)
    assert report["llm_corrupt_sample_size"] == 1
    assert report["provider_error_sample_size"] == 1
    assert report["provider_errors_by_error_type"] == {"provider_billing_or_credit_error": 1}


def test_strategy_engine_deepseek_disabled_returns_safe_fallback_without_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_DEEPSEEK_PREPROCESS", "false")
    monkeypatch.setenv("ENABLE_ANTHROPIC_FALLBACK", "false")

    cfg = BotConfig()
    engine = object.__new__(StrategyEngine)
    engine.cfg = cfg
    engine.deepseek = None
    engine.entry_gate_model = "gpt-5.4-nano"
    engine._now_iso = lambda: "2026-01-01T00:00:00+00:00"

    result = StrategyEngine._run_deepseek_preprocess(engine, "BTC-USDC", {"ticker": "BTC-USDC"})
    assert result["fallback"] is True
    assert result["fallback_reason"] == "deepseek_preprocess_disabled_gpt_nano_gate_primary"
    assert result["uncertainties"]["deepseek_disabled"] is True
