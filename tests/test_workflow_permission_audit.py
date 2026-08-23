from __future__ import annotations

import json
from pathlib import Path

from bot.approved_parameter_profile import sha256_file
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE
from tools.show_workflow_permission_audit import build_workflow_permission_audit, main


PROFILE = {
    "profile_name": "sizing_only_20_100_conservative_v1",
    "profile_version": 1,
    "parameters": {
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "100.00",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
    },
}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _env(monkeypatch, root: Path) -> None:
    monkeypatch.chdir(root)
    values = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC,ETH-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC,ETH-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": "true",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "AUTONOMOUS_ALLOW_EXITS": "true",
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
        "MARKET_ORDER_ENABLED": "true",
        "ENABLE_MARKET_ORDERS": "true",
        "ALLOW_MARKET_ORDERS": "true",
        "MODE_C_MARKET_ORDER_ACK": MODE_C_MARKET_ORDER_ACK_VALUE,
        "REPLICATION_ENABLED": "false",
        "REPLICATION_LIFECYCLE_ENABLED": "false",
        "REPLICATION_LIFECYCLE_HTTP_ENABLED": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
        "ENABLE_APPROVED_PARAMETER_PROFILE": "true",
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "100.00",
        "MIN_LIVE_ORDER_QUOTE_USDC": "20.00",
        "MAX_LIVE_ORDER_QUOTE_USDC": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_SPREAD_PCT": "0.0060",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    _write(root / "state/open_orders.json", {"orders": {}})
    _write(root / "state/positions.json", {})
    profile = root / "state/approved_parameter_profile.json"
    _write(profile, PROFILE)
    monkeypatch.setenv("APPROVED_PARAMETER_PROFILE_HASH", sha256_file(profile))


def test_full_poc_env_ready_and_outputs(tmp_path: Path, monkeypatch) -> None:
    _env(monkeypatch, tmp_path)
    report = build_workflow_permission_audit(root=tmp_path)
    assert report["read_only"] is True
    assert report["can_submit_buy"] is True
    assert report["can_submit_d3_exit"] is True
    assert report["can_market_close"] is True
    assert report["trailing_stop_status"] in {"not_implemented", "implemented_not_wired"}
    assert report["can_trailing_stop_exit"] is False
    assert report["coinbase_submit_attempted"] is False
    json_out = tmp_path / "reports/audits/workflow.json"
    md_out = tmp_path / "reports/audits/workflow.md"
    assert main(["--root", str(tmp_path), "--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    assert json_out.exists()
    assert md_out.exists()


def test_missing_entry_d3_lifecycle_flags_block(tmp_path: Path, monkeypatch) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENABLE_LIVE_ENTRY_ORDERS", "false")
    assert build_workflow_permission_audit(root=tmp_path)["can_submit_buy"] is False
    monkeypatch.setenv("ENABLE_LIVE_ENTRY_ORDERS", "true")
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false")
    assert build_workflow_permission_audit(root=tmp_path)["can_submit_d3_exit"] is False
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "true")
    monkeypatch.setenv("PHASE_C43_LIFECYCLE_APPLY_LOCAL", "false")
    assert build_workflow_permission_audit(root=tmp_path)["can_lifecycle_apply"] is False


def test_mode_b_mode_c_learning_profile_and_open_state_blocks(tmp_path: Path, monkeypatch) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MODE_B_CONTROLLED_STOP_EXIT_ACK", "wrong")
    report = build_workflow_permission_audit(root=tmp_path)
    assert report["can_controlled_stop_apply"] is False
    monkeypatch.setenv("MODE_B_CONTROLLED_STOP_EXIT_ACK", MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE)
    monkeypatch.setenv("MODE_C_MARKET_ORDER_ACK", "wrong")
    report = build_workflow_permission_audit(root=tmp_path)
    assert report["mode_c_market_orders"]["ready"] is False
    monkeypatch.setenv("MODE_C_MARKET_ORDER_ACK", MODE_C_MARKET_ORDER_ACK_VALUE)
    monkeypatch.setenv("PARAMETER_CHANGE_ALLOWED", "true")
    assert build_workflow_permission_audit(root=tmp_path)["learning_governor"]["direct_mutation_flags_false"]["PARAMETER_CHANGE_ALLOWED"] is False
    monkeypatch.setenv("PARAMETER_CHANGE_ALLOWED", "false")
    _write(tmp_path / "state/open_orders.json", {"orders": {"1": {"status": "open", "phase": "D3_controlled_live_reduce_only_exits", "side": "SELL"}}})
    report = build_workflow_permission_audit(root=tmp_path)
    assert "open_d3_exit_missing_exchange_order_id" in report["blockers"]
    _write(tmp_path / "state/open_orders.json", {"orders": {}})
    monkeypatch.setenv("APPROVED_PARAMETER_PROFILE_HASH", "bad")
    assert "approved_profile_hash_mismatch" in build_workflow_permission_audit(root=tmp_path)["blockers"]


def test_trailing_stop_status_detection_preview_only(tmp_path: Path, monkeypatch) -> None:
    _env(monkeypatch, tmp_path)
    preview = tmp_path / "bot/phase_d4_trailing_preview.py"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(
        'D4_TRAILING_PREVIEW_PHASE = "D4_trailing_preview"\n'
        'REASON = "trailing_stop_triggered_candidate_preview_only"\n'
        'required_future_ack = True\n',
        encoding="utf-8",
    )
    report = build_workflow_permission_audit(root=tmp_path)
    assert report["trailing_stop_status"] == "preview_only"
    assert report["trailing_stop"]["module_exists"] is True
    assert report["trailing_stop"]["preview_only"] is True
    assert report["can_trailing_stop_exit"] is False
