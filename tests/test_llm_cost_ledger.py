from __future__ import annotations

import json
from pathlib import Path

from bot import llm_cost_ledger


def test_record_llm_call_writes_redacted_metadata_row(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm_cost_ledger.set_current_cycle_id("full_cycle_1")

    llm_cost_ledger.record_llm_call(
        provider="openai",
        model="gpt-5.5",
        ticker="BTC-USDC",
        stage="judge_gpt_5_5",
        attempt=1,
        input_tokens=1000,
        output_tokens=200,
        latency_ms=842.3,
        call_outcome="success",
        decision_result="approve_trade",
    )

    rows = [json.loads(line) for line in (tmp_path / "logs" / "llm_cost_ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["cycle_id"] == "full_cycle_1"
    assert row["ticker"] == "BTC-USDC"
    assert row["agent"] == "final_judge"
    assert row["model"] == "gpt-5.5"
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 200
    assert row["total_tokens"] == 1200
    assert row["decision_result"] == "approve_trade"
    assert row["was_call_necessary"] == "yes"
    assert row["estimated_cost_usd"] is not None and row["estimated_cost_usd"] > 0
    assert row["cache_hit"] is False
    assert row["skipped_due_budget"] is False
    # Never log prompt/completion content -- only the known fields above.
    assert set(row.keys()) == {
        "timestamp", "cycle_id", "ticker", "agent", "stage", "provider", "model",
        "attempt", "input_tokens", "output_tokens", "total_tokens",
        "estimated_cost_usd", "latency_ms", "call_outcome", "error_type",
        "decision_result", "was_call_necessary", "cache_hit", "skipped_due_budget",
    }


def test_wait_decision_is_marked_not_necessary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm_cost_ledger.set_current_cycle_id(None)
    llm_cost_ledger.record_llm_call(
        provider="openai", model="gpt-5.5", ticker="ETH-USDC", stage="judge_gpt_5_5",
        input_tokens=500, output_tokens=100, decision_result="wait",
    )
    row = json.loads((tmp_path / "logs" / "llm_cost_ledger.jsonl").read_text().splitlines()[0])
    assert row["decision_result"] == "wait"
    assert row["was_call_necessary"] == "no"


def test_unrecognized_decision_label_collapses_to_other(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm_cost_ledger.record_llm_call(
        provider="openai", model="gpt-5.4-mini", ticker="BTC-USDC", stage="regime",
        decision_result="some made up freeform model text that should never be persisted verbatim",
    )
    row = json.loads((tmp_path / "logs" / "llm_cost_ledger.jsonl").read_text().splitlines()[0])
    assert row["decision_result"] == "other"


def test_secret_shaped_strings_are_redacted_from_scalar_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm_cost_ledger.record_llm_call(
        provider="openai",
        model="gpt-5.5",
        ticker="BTC-USDC",
        stage="judge_gpt_5_5",
        error_type="provider_auth_error: sk-ant-abcdefghijklmnopqrstuvwxyz1234567890",
        call_outcome="provider_error",
    )
    line = (tmp_path / "logs" / "llm_cost_ledger.jsonl").read_text()
    assert "sk-ant-abcdefghijklmnopqrstuvwxyz1234567890" not in line
    assert "[REDACTED]" in line


def test_failed_call_outcome_is_unknown_necessity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    llm_cost_ledger.record_llm_call(
        provider="deepseek", model="deepseek-chat", ticker="SOL-USDC", stage="deepseek_preprocess",
        call_outcome="corrupt_output", error_type="llm_output_corrupt",
    )
    row = json.loads((tmp_path / "logs" / "llm_cost_ledger.jsonl").read_text().splitlines()[0])
    assert row["was_call_necessary"] == "unknown"
    assert row["call_outcome"] == "corrupt_output"


def test_estimate_cost_usd_uses_pricing_table():
    cost = llm_cost_ledger.estimate_cost_usd("gpt-5.5", 1000, 1000)
    pricing = llm_cost_ledger.MODEL_PRICING_PER_1K_USD["gpt-5.5"]
    assert cost == round(pricing["input_per_1k"] + pricing["output_per_1k"], 8)


def test_estimate_cost_usd_unknown_model_returns_none():
    assert llm_cost_ledger.estimate_cost_usd("totally-unknown-model", 1000, 1000) is None


def test_estimate_cost_usd_missing_tokens_returns_none():
    assert llm_cost_ledger.estimate_cost_usd("gpt-5.5", None, 1000) is None


def test_cycle_context_manager_restores_previous_value():
    llm_cost_ledger.set_current_cycle_id("outer")
    with llm_cost_ledger.cycle_context("inner"):
        assert llm_cost_ledger.get_current_cycle_id() == "inner"
    assert llm_cost_ledger.get_current_cycle_id() == "outer"


def test_disabled_via_cfg_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = type("Cfg", (), {"llm_cost_ledger_enabled": False})()
    llm_cost_ledger.record_llm_call(
        provider="openai", model="gpt-5.5", ticker="BTC-USDC", stage="judge_gpt_5_5", cfg=cfg,
    )
    assert not (tmp_path / "logs" / "llm_cost_ledger.jsonl").exists()


def test_record_llm_call_never_raises_on_bad_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # input_tokens deliberately not coercible to int -- must not raise.
    llm_cost_ledger.record_llm_call(
        provider="openai", model="gpt-5.5", ticker="BTC-USDC", stage="judge_gpt_5_5",
        input_tokens="not-a-number",  # type: ignore[arg-type]
    )
