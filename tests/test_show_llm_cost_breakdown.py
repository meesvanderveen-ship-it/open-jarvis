from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.show_llm_cost_breakdown import (
    build_cost_breakdown,
    detect_duplicate_first_attempts,
    load_ledger_rows,
    parse_since,
)


def _row(**overrides):
    base = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle_id": "full_1",
        "ticker": "BTC-USDC",
        "agent": "final_judge",
        "stage": "judge_gpt_5_5",
        "provider": "openai",
        "model": "gpt-5.5",
        "attempt": 1,
        "input_tokens": 1000,
        "output_tokens": 200,
        "total_tokens": 1200,
        "estimated_cost_usd": 0.0045,
        "latency_ms": 800.0,
        "call_outcome": "success",
        "error_type": None,
        "decision_result": "wait",
        "was_call_necessary": "no",
        "cache_hit": False,
        "skipped_due_budget": False,
    }
    base.update(overrides)
    return base


def _write_ledger(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_parse_since_duration_shorthand():
    now = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_since("24h", now=now) == now - timedelta(hours=24)
    assert parse_since("7d", now=now) == now - timedelta(days=7)
    assert parse_since("30m", now=now) == now - timedelta(minutes=30)


def test_parse_since_iso_timestamp():
    parsed = parse_since("2026-06-01T00:00:00Z")
    assert parsed.year == 2026 and parsed.month == 6 and parsed.day == 1


def test_load_ledger_rows_filters_by_since(tmp_path):
    path = tmp_path / "logs" / "llm_cost_ledger.jsonl"
    old_row = _row(timestamp=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat())
    new_row = _row(timestamp=datetime.now(timezone.utc).isoformat())
    _write_ledger(path, [old_row, new_row])

    rows = load_ledger_rows(path, since=datetime.now(timezone.utc) - timedelta(hours=1))
    assert len(rows) == 1
    assert rows[0]["timestamp"] == new_row["timestamp"]


def test_load_ledger_rows_skips_malformed_lines(tmp_path):
    path = tmp_path / "logs" / "llm_cost_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_row()) + "\nnot valid json\n\n", encoding="utf-8")
    rows = load_ledger_rows(path)
    assert len(rows) == 1


def test_build_cost_breakdown_aggregates_totals_and_groups(tmp_path):
    path = tmp_path / "llm_cost_ledger.jsonl"
    rows = [
        _row(ticker="BTC-USDC", agent="final_judge", model="gpt-5.5", estimated_cost_usd=0.01, decision_result="wait", was_call_necessary="no"),
        _row(ticker="ETH-USDC", agent="analyst_regime", model="gpt-5.4-mini", estimated_cost_usd=0.001, decision_result="approve_trade", was_call_necessary="yes"),
        _row(ticker="BTC-USDC", agent="entry_gate", model="gpt-5.4-nano", estimated_cost_usd=0.0001, decision_result="skip", was_call_necessary="no"),
    ]
    _write_ledger(path, rows)

    report = build_cost_breakdown(ledger_path=path, since="30d")

    assert report["total_calls"] == 3
    assert round(report["total_estimated_cost_usd"], 4) == round(0.01 + 0.001 + 0.0001, 4)
    assert report["by_agent"]["final_judge"]["calls"] == 1
    assert report["by_ticker"]["BTC-USDC"]["calls"] == 2
    assert report["by_model"]["gpt-5.5"]["estimated_cost_usd"] == 0.01
    assert report["no_action_calls"] == 2
    assert report["top_10_expensive_calls"][0]["ticker"] == "BTC-USDC"
    assert report["top_10_expensive_calls"][0]["estimated_cost_usd"] == 0.01
    assert report["read_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False


def test_build_cost_breakdown_by_filter_adds_selected_breakdown(tmp_path):
    path = tmp_path / "llm_cost_ledger.jsonl"
    _write_ledger(path, [_row()])
    report = build_cost_breakdown(ledger_path=path, since="30d", by="agent")
    assert report["selected_breakdown_by"] == "agent"
    assert report["selected_breakdown"] == report["by_agent"]


def test_build_cost_breakdown_empty_ledger_does_not_crash(tmp_path):
    path = tmp_path / "missing.jsonl"
    report = build_cost_breakdown(ledger_path=path, since="24h")
    assert report["total_calls"] == 0
    assert report["total_estimated_cost_usd"] == 0.0
    assert report["no_action_cost_pct"] == 0.0


def test_detect_duplicate_first_attempts_flags_same_cycle_ticker_stage():
    rows = [
        _row(cycle_id="full_1", ticker="BTC-USDC", stage="judge_gpt_5_5", attempt=1),
        _row(cycle_id="full_1", ticker="BTC-USDC", stage="judge_gpt_5_5", attempt=1),
        _row(cycle_id="full_1", ticker="ETH-USDC", stage="judge_gpt_5_5", attempt=1),
    ]
    duplicates = detect_duplicate_first_attempts(rows)
    assert len(duplicates) == 1
    assert duplicates[0]["ticker"] == "BTC-USDC"
    assert duplicates[0]["first_attempt_count"] == 2


def test_detect_duplicate_first_attempts_ignores_legitimate_retries():
    rows = [
        _row(cycle_id="full_1", ticker="BTC-USDC", stage="judge_gpt_5_5", attempt=1),
        _row(cycle_id="full_1", ticker="BTC-USDC", stage="judge_gpt_5_5", attempt=2),
        _row(cycle_id="full_1", ticker="BTC-USDC", stage="judge_gpt_5_5", attempt=3),
    ]
    assert detect_duplicate_first_attempts(rows) == []


def test_no_action_cost_pct_computed_correctly(tmp_path):
    path = tmp_path / "llm_cost_ledger.jsonl"
    rows = [
        _row(estimated_cost_usd=1.0, was_call_necessary="no"),
        _row(estimated_cost_usd=1.0, was_call_necessary="yes"),
    ]
    _write_ledger(path, rows)
    report = build_cost_breakdown(ledger_path=path, since="30d")
    assert report["no_action_cost_pct"] == 50.0
