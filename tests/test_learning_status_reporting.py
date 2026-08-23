from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.show_autonomous_live_run_status import build_autonomous_live_run_status
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report
from tools.show_neural_shadow_policy_status import build_neural_shadow_policy_status


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _full_env(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.chdir(root)
    values = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test-key",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "PHASE_C_MAX_ORDER_QUOTE": "20.00",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": "true",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_ENABLED": "true",
        "NEURAL_SHADOW_POLICY_TRAINING_ENABLED": "true",
        "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_AGREEMENT_REQUIRED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    _write(root / "state/open_orders.json", {"orders": {}})
    _write(root / "state/positions.json", {})


def test_status_reports_approved_profile_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _full_env(monkeypatch, tmp_path)
    payload = {
        "profile_name": "test",
        "profile_version": 1,
        "parameters": {
            "MAX_SPREAD_PCT": "0.0060",
            "DEFAULT_QUOTE_SIZE_USDC": "20.00",
            "MAX_NOTIONAL_USD": "20.00",
            "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
            "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
            "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
            "PHASE_C_MAX_ORDER_QUOTE": "20.00",
            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
        },
    }
    path = tmp_path / "state/approved_parameter_profile.json"
    _write(path, payload)
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "true")
    monkeypatch.setenv("APPROVED_PARAMETER_PROFILE_HASH", hashlib.sha256(path.read_bytes()).hexdigest())

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-12T00:00:00Z")

    assert report["learning_status"]["learning_mode"] == "approved_profile_active"
    assert report["neural_learning_status"]["enabled"] is True
    assert report["neural_learning_status"]["execution_allowed"] is False
    assert report["approved_profile_status"]["loaded"] is True
    assert report["approved_profile_status"]["hash_valid"] is True


def test_status_mode_b_precedence_when_apply_flag_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _full_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENABLE_CONTROLLED_STOP_MARKET_EXITS", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY", "true")
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")

    report = build_autonomous_live_run_status(root=tmp_path)

    assert report["mode"] == "mode_b_apply_enabled"
    assert "learning_status" in report
    assert "neural_learning_status" in report


def test_neural_status_tool_reports_neural_learning_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _full_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")

    report = build_neural_shadow_policy_status(root=tmp_path)

    assert report["coinbase_call_attempted"] is False
    assert report["llm_call_attempted"] is False
    assert report["neural_learning_status"]["enabled"] is True
    assert report["neural_learning_status"]["execution_allowed"] is False
