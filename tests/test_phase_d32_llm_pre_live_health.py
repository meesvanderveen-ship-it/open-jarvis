from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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

from bot.llm_clients import (
    _dedupe_repeated_fragments,
    _ensure_only_allowed_keys,
    _extract_first_json_object,
    _write_llm_corrupt_log,
    _write_llm_provider_error_log,
    _write_llm_schema_drift_log,
    LLMOutputCorruptError,
)
from bot.phase_d31_lifecycle_readiness import build_phase_d31_lifecycle_readiness_report
from bot.phase_d32_llm_pre_live_health import (
    D32_BLOCKED,
    D32_READY,
    build_phase_d32_llm_pre_live_health_report,
)


def _cfg(**overrides):
    base = dict(
        enable_deepseek_preprocess=False,
        enable_anthropic_fallback=False,
        enable_phase_d32_llm_pre_live_health=True,
        phase_d32_llm_health_window_minutes=240,
        phase_d32_block_on_recent_llm_corrupt=True,
        phase_d32_block_on_recent_provider_errors=True,
        llm_context_hygiene_enabled=True,
        llm_repeated_fragment_max_repeats=2,
        llm_payload_string_max_chars=1000,
        llm_payload_hygiene_max_depth=8,
        llm_corrupt_logging_enabled=True,
        llm_provider_error_logging_enabled=True,
        llm_corrupt_max_raw_chars=300,
        openai_model="gpt-5.4-mini",
        openai_analyst_model="gpt-5.4-mini",
        openai_judge_model="gpt-5.5",
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        autonomous_entry_only_first=True,
        autonomous_require_post_only=True,
        enable_phase_d2_position_executor=True,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_max_order_quote="25.00",
        autonomous_max_order_quote="25.00",
        phase_c_max_open_entry_orders=4,
        autonomous_max_open_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_new_orders_per_cycle=1,
        phase_d3_max_open_exit_orders=4,
        phase_c_allowed_tickers=["BTC-USDC", "SUI-USDC"],
        allowed_tickers=["BTC-USDC", "SUI-USDC"],
        enable_phase_d1_exit_orderbook_scaffold=True,
        enable_phase_d1_actual_exit_submit=False,
        phase_d1_max_exit_order_quote="25.00",
        phase_d1_max_open_exit_orders=4,
        phase_d1_require_reduce_only=True,
        phase_d1_exit_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _EmptyOrderStore:
    def open_order_counts(self):
        return {"total_open_orders": 0, "by_status": {}, "by_ticker": {}}

    def all_orders(self):
        """Ontbrak, terwijl de echte OrderStore hem wel heeft.

        De code onder test loopt via `store.all_orders()`, dus deze dubbel
        liep stuk op een AttributeError voordat de eigenlijke assertie aan bod
        kwam. Een lege store levert een lege lijst op -- consistent met alle
        andere methodes hieronder en met bot/order_store.py::all_orders.
        """
        return []

    def list_orders(self, *args, **kwargs):
        return []

    def open_orders(self, *args, **kwargs):
        return []

    def open_entry_orders(self, *args, **kwargs):
        return []

    def open_exit_orders(self, *args, **kwargs):
        return []


class _EmptyStateStore:
    def get_positions(self):
        return {}

    def get_position(self, ticker):
        return None


def test_d32_ready_when_logs_are_empty(tmp_path):
    cfg = _cfg()
    (tmp_path / "logs").mkdir()
    report = build_phase_d32_llm_pre_live_health_report(cfg=cfg, project_root=tmp_path)
    assert report["status"] == D32_READY
    assert report["ready"] is True
    assert report["blockers"] == []
    assert "no_recent_llm_corrupt_outputs" in report["passed_checks"]


def test_d32_blocks_recent_fatal_provider_error(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    row = {
        "generated_at": (now - timedelta(minutes=5)).isoformat(),
        "provider": "anthropic",
        "model": "claude-opus-4-6",
        "ticker": "BTC-USDC",
        "stage": "judge",
        "error_type": "provider_billing_or_credit_error",
        "fatal_provider_error": True,
        "error": "credit balance is too low",
    }
    (logs / "llm_provider_errors.jsonl").write_text(json.dumps(row) + "\n")
    report = build_phase_d32_llm_pre_live_health_report(cfg=_cfg(), project_root=tmp_path, now=now)
    assert report["status"] == D32_BLOCKED
    assert "recent_fatal_provider_errors:1" in report["blockers"]


def test_d32_blocks_recent_corrupt_output(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    row = {
        "generated_at": (now - timedelta(minutes=2)).isoformat(),
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "ticker": "SUI-USDC",
        "stage": "regime",
        "error_type": "llm_output_corrupt",
        "error": "no_valid_json_object_found",
    }
    (logs / "llm_corrupt.jsonl").write_text(json.dumps(row) + "\n")
    report = build_phase_d32_llm_pre_live_health_report(cfg=_cfg(), project_root=tmp_path, now=now)
    assert report["status"] == D32_BLOCKED
    assert "recent_llm_corrupt_outputs:1" in report["blockers"]


def test_extra_schema_keys_are_accepted_and_filtered_without_approval_promotion():
    allowed = ["decision", "ticker", "side", "size_quote", "reasons"]
    payload = {
        "decision": "wait",
        "ticker": "BTC-USDC",
        "side": "NONE",
        "size_quote": 0,
        "reasons": ["no clean setup"],
        "recommended_action": "approve_trade",
        "primary_strategy": "live-submit",
    }

    filtered = _ensure_only_allowed_keys(payload, allowed, require_all=True, drop_unknown_keys=False)

    assert filtered == {
        "decision": "wait",
        "ticker": "BTC-USDC",
        "side": "NONE",
        "size_quote": 0,
        "reasons": ["no clean setup"],
    }
    assert "recommended_action" not in filtered
    assert "primary_strategy" not in filtered


def test_missing_required_schema_key_stays_rejected():
    payload = {
        "decision": "wait",
        "ticker": "BTC-USDC",
        "side": "NONE",
        "reasons": ["no clean setup"],
    }

    try:
        _ensure_only_allowed_keys(payload, ["decision", "ticker", "side", "size_quote", "reasons"], require_all=True)
    except LLMOutputCorruptError as exc:
        assert "missing_required_keys" in str(exc)
    else:
        raise AssertionError("missing required key should be rejected")


def test_invalid_json_stays_rejected():
    try:
        _extract_first_json_object('{"decision": "wait", ')
    except LLMOutputCorruptError as exc:
        assert str(exc) == "no_valid_json_object_found"
    else:
        raise AssertionError("invalid JSON should be rejected")


def test_d32_reports_schema_drift_separately_from_corrupt_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    cfg = _cfg()
    _write_llm_schema_drift_log(
        "openai",
        "gpt-5.4-mini",
        "BTC-USDC",
        "synth",
        ["primary_strategy", "recommended_action"],
        cfg,
    )

    row = json.loads(Path("logs/llm_schema_drift.jsonl").read_text().splitlines()[0])
    row["generated_at"] = (now - timedelta(minutes=1)).isoformat()
    Path("logs/llm_schema_drift.jsonl").write_text(json.dumps(row) + "\n")

    report = build_phase_d32_llm_pre_live_health_report(cfg=cfg, project_root=tmp_path, now=now)

    assert report["status"] == D32_READY
    assert report["counts"]["recent_corrupt_rows"] == 0
    assert report["counts"]["recent_schema_drift_rows"] == 1
    assert "recent_llm_corrupt_outputs:1" not in report["blockers"]
    assert any("recent_llm_schema_drift_extra_keys_ignored:1" == w for w in report["warnings"])
    assert report["recent_schema_drift"][0]["unknown_keys"] == ["primary_strategy", "recommended_action"]


def test_d32_undated_legacy_logs_warn_but_do_not_block(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "llm_corrupt.jsonl").write_text(json.dumps({"provider": "deepseek", "error": "old"}) + "\n")
    report = build_phase_d32_llm_pre_live_health_report(cfg=_cfg(), project_root=tmp_path)
    assert report["ready"] is True
    assert any("undated_legacy_llm_log_rows_present" in w for w in report["warnings"])


def test_d32_writers_add_generated_at_and_fatal_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _cfg(llm_corrupt_max_raw_chars=120)
    _write_llm_corrupt_log("openai", "gpt", "BTC-USDC", "stage", "bad" * 100, "broken", cfg)
    _write_llm_provider_error_log("anthropic", "claude", "BTC-USDC", "judge", "credit balance is too low", "provider_billing_or_credit_error", cfg)

    corrupt = json.loads(Path("logs/llm_corrupt.jsonl").read_text().splitlines()[0])
    provider = json.loads(Path("logs/llm_provider_errors.jsonl").read_text().splitlines()[0])
    assert corrupt["generated_at"]
    assert provider["generated_at"]
    assert provider["fatal_provider_error"] is True


def test_d32_dedupes_short_repeated_indicator_fragments():
    text = ("1h bb_upper 10.828; 1h price above bb_upper; 1h ADX 30; " * 40).strip()
    out, deduped, count = _dedupe_repeated_fragments(text, max_repeats=2)
    assert deduped is True
    assert count > 50
    assert len(out) < len(text) / 2


def test_d31_includes_d32_health_and_blocks_when_recent_corrupt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    now = datetime.now(timezone.utc)
    (tmp_path / "logs" / "llm_corrupt.jsonl").write_text(json.dumps({
        "generated_at": now.isoformat(),
        "provider": "openai",
        "stage": "entry_gate",
        "error_type": "llm_output_corrupt",
        "error": "broken",
    }) + "\n")
    report = build_phase_d31_lifecycle_readiness_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_store=_EmptyOrderStore(),
        state_store=_EmptyStateStore(),
    )
    assert report["ready_for_controlled_entry_only_arming"] is False
    assert "recent_llm_corrupt_outputs:1" in report["blockers"]
    assert report["llm_pre_live_health"]["status"] == D32_BLOCKED
