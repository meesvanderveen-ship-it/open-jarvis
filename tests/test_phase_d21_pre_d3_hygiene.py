from __future__ import annotations

import json
import sys
import types
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
    _write_llm_corrupt_log,
    compact_payload_for_llm,
)
from bot.phase_d2_position_executor import (
    D2_PLAN_STATUS_NO_POSITION,
    build_phase_d2_position_executor_report,
    is_d2_manageable_open_position,
)


def _cfg(**overrides):
    base = dict(
        enable_phase_d2_position_executor=True,
        phase_d2_min_expected_net_edge_pct="0.0125",
        phase_d2_min_reward_to_fee_ratio="3.0",
        phase_d2_min_reward_to_risk_ratio="1.5",
        phase_d2_estimated_entry_fee_pct="0.0040",
        phase_d2_estimated_exit_fee_pct="0.0040",
        phase_d2_estimated_spread_slippage_pct="0.0020",
        phase_d2_fee_safety_buffer_pct="0.0025",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        llm_context_hygiene_enabled=True,
        llm_repeated_fragment_max_repeats=2,
        llm_payload_string_max_chars=500,
        llm_payload_hygiene_max_depth=8,
        llm_corrupt_logging_enabled=True,
        llm_corrupt_max_raw_chars=300,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _GhostStateStore:
    def get_position(self, ticker):
        return {
            "ticker": ticker,
            "status": "open",
            "order_id": "ghost-zero-base",
            "entry_price": "67311.6",
            "position_size_base": "0",
            "position_size_quote": "0",
        }

    def get_positions(self):
        return {
            "ghost-zero-base": self.get_position("BTC-USDC"),
            "diagnostic": {
                "ticker": "TEST-BUYKEEP",
                "status": "open",
                "position_size_base": "0.5",
                "entry_price": "100",
                "paper_only": True,
            },
        }


def test_d21_ignores_zero_base_and_diagnostic_positions_before_d3():
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        state_store=_GhostStateStore(),
    )

    assert report["status"] == D2_PLAN_STATUS_NO_POSITION
    assert report["open_position_count"] == 0
    assert report["ignored_position_count"] == 2
    assert report["selected_position_present"] is False
    assert report["raw_selected_position_present"] is True
    assert "ghost_or_zero_base_selected_position_ignored" in report["warnings"]
    assert report["live_sell_submit_attempted_by_this_tool"] is False
    assert report["live_sell_order_submitted"] is False


def test_d21_manageable_position_filter_accepts_real_open_and_rejects_test_or_zero():
    assert is_d2_manageable_open_position({
        "ticker": "ADA-USDC",
        "status": "open",
        "position_size_base": "100",
        "entry_price": "0.25",
    }) is True
    assert is_d2_manageable_open_position({
        "ticker": "ADA-USDC",
        "status": "open",
        "position_size_base": "0",
        "entry_price": "0.25",
    }) is False
    assert is_d2_manageable_open_position({
        "ticker": "TEST-BUYKEEP",
        "status": "open",
        "position_size_base": "0.5",
        "entry_price": "100",
    }) is False


def test_d21_llm_fragment_dedup_and_payload_compaction():
    repeated = "; ".join(["1h ADX strong and 4h EMA50 above EMA200"] * 8)
    deduped, changed, count = _dedupe_repeated_fragments(repeated, max_repeats=2)
    assert changed is True
    assert count == 6
    assert deduped.count("1h ADX strong") == 2

    payload = {"ticker": "LINK-USDC", "context": repeated}
    compacted = compact_payload_for_llm(payload, _cfg())
    assert compacted["ticker"] == "LINK-USDC"
    assert compacted["context"].count("1h ADX strong") == 2
    assert "deduplicated" in compacted["context"]


def test_d21_corrupt_log_contains_hygiene_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    noisy = "; ".join(["1h ADX strong and 4h EMA50 above EMA200"] * 20)
    _write_llm_corrupt_log("openai", "gpt", "SUI-USDC", "regime", noisy, "no_valid_json_object_found", _cfg())
    row = json.loads(Path("logs/llm_corrupt.jsonl").read_text().splitlines()[0])
    assert row["hygiene"]["deduplicated"] is True
    assert row["hygiene"]["deduplicated_fragments"] >= 1
    assert row["raw_text_truncated"] in {True, False}
