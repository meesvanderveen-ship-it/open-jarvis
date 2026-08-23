from __future__ import annotations

import json
from pathlib import Path

from bot.config import BotConfig
from bot.phase_c_live_submitter import (
    build_phase_c_dry_run_candidate,
    run_phase_c_live_submit_dry_run,
)


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_phase_c21_current_config_dry_run_writes_disabled_diagnostic_audit(tmp_path):
    cfg = BotConfig()
    audit_path = tmp_path / "phase_c_live_submit.jsonl"

    result = run_phase_c_live_submit_dry_run(
        cfg=cfg,
        ticker="BTC-USDC",
        audit_path=audit_path,
        simulate_ready_guard=False,
        append_audit=True,
    )

    assert audit_path.exists()
    rows = _read_jsonl(audit_path)
    assert len(rows) == 1
    row = rows[0]
    assert row == result
    assert row["phase"] == "C21_live_submit_dry_run_audit"
    assert row["diagnostic"] is True
    assert row["dry_run"] is True
    assert row["live_submission_attempted"] is False
    assert row["live_order_submitted"] is False
    assert "phase_c_guard_did_not_allow_live_submit" in row["hard_block_reasons"]
    assert "phase_c_actual_coinbase_submit_disabled" in row["hard_block_reasons"]
    assert "submit_live_argument_false" in row["hard_block_reasons"]
    assert "coinbase_client_not_provided" in row["hard_block_reasons"]


def test_phase_c21_simulate_ready_guard_still_blocks_actual_submit(tmp_path):
    cfg = BotConfig()
    audit_path = tmp_path / "phase_c_live_submit.jsonl"

    result = run_phase_c_live_submit_dry_run(
        cfg=cfg,
        ticker="BTC-USDC",
        audit_path=audit_path,
        simulate_ready_guard=True,
        append_audit=True,
    )

    assert result["simulate_ready_guard"] is True
    assert result["guard_result_full"]["guard_allows_live_submit"] is True
    assert result["payload"]["accepted"] is True
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "phase_c_actual_coinbase_submit_disabled" in result["hard_block_reasons"]
    assert "submit_live_argument_false" in result["hard_block_reasons"]
    assert "coinbase_client_not_provided" in result["hard_block_reasons"]
    assert "phase_c_guard_did_not_allow_live_submit" not in result["hard_block_reasons"]


def test_phase_c21_dry_run_does_not_mutate_real_config():
    cfg = BotConfig()
    before = {
        "enable_phase_c_live_small_limit_orders": cfg.enable_phase_c_live_small_limit_orders,
        "enable_live_limit_orders": cfg.enable_live_limit_orders,
        "enable_live_entry_orders": cfg.enable_live_entry_orders,
        "phase_c_allowed_tickers": list(cfg.phase_c_allowed_tickers),
        "enable_phase_c_actual_coinbase_submit": cfg.enable_phase_c_actual_coinbase_submit,
    }

    run_phase_c_live_submit_dry_run(
        cfg=cfg,
        ticker="BTC-USDC",
        simulate_ready_guard=True,
        append_audit=False,
    )

    after = {
        "enable_phase_c_live_small_limit_orders": cfg.enable_phase_c_live_small_limit_orders,
        "enable_live_limit_orders": cfg.enable_live_limit_orders,
        "enable_live_entry_orders": cfg.enable_live_entry_orders,
        "phase_c_allowed_tickers": list(cfg.phase_c_allowed_tickers),
        "enable_phase_c_actual_coinbase_submit": cfg.enable_phase_c_actual_coinbase_submit,
    }
    assert after == before


def test_phase_c21_diagnostic_candidate_is_entry_only_and_paper_only():
    cfg = BotConfig()
    candidate = build_phase_c_dry_run_candidate(cfg=cfg, ticker="ETH-USDC")
    order_intent = candidate["order_intent"]
    assert order_intent["side"] == "BUY"
    assert order_intent["execution_action"] == "place_limit_buy"
    assert order_intent["paper_only"] is True
    assert order_intent["diagnostic"] is True
    assert candidate["risk"]["accepted"] is True
