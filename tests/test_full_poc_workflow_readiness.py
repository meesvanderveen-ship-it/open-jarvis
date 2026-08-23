from __future__ import annotations

import json
from pathlib import Path

from bot.approved_parameter_profile import sha256_file
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report


PROFILE = {
    "parameters": {
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "DEFAULT_QUOTE_SIZE_USDC": "50.00",
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
        "MAX_NOTIONAL_USD": "100.00",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_SPREAD_PCT": "0.0060",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "120.00",
    },
    "profile_name": "dynamic_entry_50_100_fee_aware_v1",
    "profile_version": 1,
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_profile(root: Path, monkeypatch) -> None:
    path = root / "state/approved_parameter_profile.json"
    _write_json(path, PROFILE)
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "true")
    monkeypatch.setenv("APPROVED_PARAMETER_PROFILE_HASH", sha256_file(path))


def _seed_empty_state(root: Path) -> None:
    _write_json(root / "state/open_orders.json", {"orders": {}})
    _write_json(root / "state/positions.json", {})


def _set_full_poc_env(monkeypatch, root: Path) -> None:
    monkeypatch.chdir(root)
    env = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test-key",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC,ETH-USDC,SOL-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC,ETH-USDC,SOL-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_D2_POSITION_EXECUTOR": "true",
        "ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS": "true",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_D3_MAX_OPEN_EXIT_ORDERS": "3",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": "true",
        "PHASE_C43_LIFECYCLE_APPLY_LOCAL": "true",
        "PHASE_C43_LIFECYCLE_BUILD_D2_PLAN": "true",
        "PHASE_C43_LIFECYCLE_PERSIST_D2_PLAN": "true",
        "PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW": "true",
        "ENABLE_CONTROLLED_STOP_MARKET_EXITS": "true",
        "ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL": "true",
        "ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT": "true",
        "ENABLE_AUTONOMOUS_STOP_EXIT_APPLY": "true",
        "MODE_B_CONTROLLED_STOP_EXIT_ACK": MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
        "MARKET_ORDER_ENABLED": "false",
        "ENABLE_MARKET_ORDERS": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "MODE_C_MARKET_ORDER_ACK": MODE_C_MARKET_ORDER_ACK_VALUE,
        "REPLICATION_ENABLED": "false",
        "REPLICATION_LIFECYCLE_ENABLED": "false",
        "REPLICATION_LIFECYCLE_HTTP_ENABLED": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_TRAINING_ENABLED": "true",
        "DEFAULT_QUOTE_SIZE_USDC": "50.00",
        "MAX_NOTIONAL_USD": "100.00",
        "MIN_LIVE_ORDER_QUOTE_USDC": "50.00",
        "MAX_LIVE_ORDER_QUOTE_USDC": "100.00",
        "ENABLE_DYNAMIC_ENTRY_SIZING": "true",
        "MIN_DYNAMIC_ENTRY_QUOTE_USDC": "50.00",
        "MAX_DYNAMIC_ENTRY_QUOTE_USDC": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "120.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "3",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_SPREAD_PCT": "0.0060",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
        "ENABLE_BOUNDED_EXPLORATION_MODE": "false",
        "EXPLORATION_ALLOW_MARKET_ORDERS": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _seed_profile(root, monkeypatch)
    _seed_empty_state(root)


def test_full_poc_with_mode_b_mode_c_and_replication_false_is_ready(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T12:00:00Z")
    poc = report["poc_full_workflow_readiness"]

    assert report["recommendation"] == "ready_for_full_poc_live_run_no_replication"
    assert poc == {
        "ready": True,
        "core_entries_enabled": True,
        "core_exits_enabled": True,
        "d2_d3_enabled": True,
        "entry_lifecycle_enabled": True,
        "exit_lifecycle_enabled": True,
        "controlled_stop_exit_apply_enabled": True,
        "mode_b_ack_valid": True,
        "market_orders_enabled": False,
        "mode_c_ack_valid": True,
        "replication_disabled": True,
        "direct_parameter_mutation_disabled": True,
        "neural_diagnostic_only": True,
        "open_orders": 0,
        "open_positions": 0,
        "blockers": [],
    }
    assert report["approved_profile_status"]["hash_valid"] is True
    assert report["approved_profile_status"]["parameters"]["DEFAULT_QUOTE_SIZE_USDC"] == "50.00"
    assert report["market_order_status"]["status"] == "disabled"
    assert report["mode_c_market_order_readiness"]["status"] == "disabled"
    assert report["live_order_size_policy"]["market_orders_allowed"] is False


def test_full_poc_allows_default_quote_50_inside_live_rails(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    profile = dict(PROFILE)
    profile["parameters"] = dict(PROFILE["parameters"])
    profile["parameters"]["DEFAULT_QUOTE_SIZE_USDC"] = "50.00"
    path = tmp_path / "state/approved_parameter_profile.json"
    _write_json(path, profile)
    monkeypatch.setenv("DEFAULT_QUOTE_SIZE_USDC", "50.00")
    monkeypatch.setenv("APPROVED_PARAMETER_PROFILE_HASH", sha256_file(path))

    report = build_full_autonomous_run_readiness_report(root=tmp_path)

    assert report["poc_full_workflow_readiness"]["ready"] is True
    assert "default_quote_not_50" not in report["poc_full_workflow_readiness"]["blockers"]
    assert "default_quote_outside_live_quote_rails" not in report["poc_full_workflow_readiness"]["blockers"]
    assert report["approved_profile_status"]["parameters"]["DEFAULT_QUOTE_SIZE_USDC"] == "50.00"


def test_full_poc_missing_mode_b_ack_blocks(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MODE_B_CONTROLLED_STOP_EXIT_ACK", raising=False)
    report = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert "mode_b_stop_exit_apply_ack_missing" in report["poc_full_workflow_readiness"]["blockers"]
    assert report["poc_full_workflow_readiness"]["ready"] is False


def test_full_poc_missing_mode_c_ack_does_not_block_orderbook_only_route(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    monkeypatch.delenv("MODE_C_MARKET_ORDER_ACK", raising=False)
    report = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert "mode_c_market_order_ack_missing" not in report["poc_full_workflow_readiness"]["blockers"]
    assert report["poc_full_workflow_readiness"]["ready"] is True
    assert report["live_order_size_policy"]["market_orders_allowed"] is False


def test_full_poc_replication_true_blocks(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "true")
    report = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert "market_orders_enabled_with_replication" in report["poc_full_workflow_readiness"]["blockers"]
    assert report["poc_full_workflow_readiness"]["replication_disabled"] is False
    assert report["live_order_size_policy"]["market_orders_allowed"] is False


def test_full_poc_direct_parameter_mutation_true_blocks(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PARAMETER_CHANGE_ALLOWED", "true")
    report = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert "direct_learning_to_execution_flags_enabled" in report["poc_full_workflow_readiness"]["blockers"]
    assert report["poc_full_workflow_readiness"]["direct_parameter_mutation_disabled"] is False


def test_full_poc_neural_diagnostic_only_does_not_block(tmp_path: Path, monkeypatch) -> None:
    _set_full_poc_env(monkeypatch, tmp_path)
    monkeypatch.setenv("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED", "false")
    monkeypatch.setenv("NEURAL_SHADOW_POLICY_TRAINING_ENABLED", "true")
    report = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert report["poc_full_workflow_readiness"]["neural_diagnostic_only"] is True
    assert "neural_shadow_policy_execution_allowed" not in report["poc_full_workflow_readiness"]["blockers"]
