from __future__ import annotations

import json
from pathlib import Path

from bot.approved_parameter_profile import sha256_file
from tools.activate_sizing_only_20_100_profile import (
    ACK,
    PROFILE_NAME,
    build_activation_report,
    build_candidate_payload,
    main as sizing_main,
    write_candidate,
)


def _write_safe_root(root: Path) -> None:
    (root / "state").mkdir(parents=True)
    (root / "reports/backtests").mkdir(parents=True)
    (root / "state/open_orders.json").write_text(json.dumps({"orders": {}}), encoding="utf-8")
    (root / "state/positions.json").write_text(json.dumps({
        "BTC-USDC": {"ticker": "BTC-USDC", "status": "closed", "position_size_base": "0"}
    }), encoding="utf-8")
    (root / ".env").write_text(
        "\n".join([
            "REPLICATION_ENABLED=false",
            "REPLICATION_LIFECYCLE_ENABLED=false",
            "REPLICATION_LIFECYCLE_HTTP_ENABLED=false",
            "MARKET_ORDER_ENABLED=false",
            "ENABLE_MARKET_ORDERS=false",
            "ALLOW_MARKET_ORDERS=false",
            "LEARNING_TO_EXECUTION_ALLOWED=false",
            "LIVE_LEARNING_ALLOWED=false",
            "PARAMETER_CHANGE_ALLOWED=false",
            "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=false",
        ]) + "\n",
        encoding="utf-8",
    )
    (root / "state/approved_parameter_profile.json").write_text(json.dumps({
        "profile_name": "active",
        "profile_version": 1,
        "parameters": {"DEFAULT_QUOTE_SIZE_USDC": "20.00", "MAX_NOTIONAL_USD": "20.00"},
    }, sort_keys=True), encoding="utf-8")


def _set_minimal_config_env(monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC")
    monkeypatch.setenv("ENABLE_FULL_WORKFLOW_LIVE_MODE", "true")
    for key in [
        "ENABLE_LIMIT_ORDER_MANAGER",
        "ENABLE_LIVE_LIMIT_ORDERS",
        "ENABLE_LIVE_ENTRY_ORDERS",
        "ENABLE_LIVE_EXIT_ORDERS",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE",
        "AUTONOMOUS_ALLOW_EXITS",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL",
    ]:
        monkeypatch.setenv(key, "true")
    monkeypatch.setenv("AUTONOMOUS_ENTRY_ONLY_FIRST", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "false")
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    monkeypatch.setenv("REPLICATION_LIFECYCLE_ENABLED", "false")
    monkeypatch.setenv("REPLICATION_LIFECYCLE_HTTP_ENABLED", "false")
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "false")
    monkeypatch.setenv("ENABLE_MARKET_ORDERS", "false")
    monkeypatch.setenv("ALLOW_MARKET_ORDERS", "false")
    monkeypatch.setenv("LEARNING_TO_EXECUTION_ALLOWED", "false")
    monkeypatch.setenv("LIVE_LEARNING_ALLOWED", "false")
    monkeypatch.setenv("PARAMETER_CHANGE_ALLOWED", "false")
    monkeypatch.setenv("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED", "false")


def test_sizing_only_candidate_is_safe_and_scope_limited() -> None:
    payload = build_candidate_payload(generated_at="2026-06-14T00:00:00Z")
    assert payload["profile_name"] == PROFILE_NAME
    assert payload["safe_to_live_activate_now"] is True
    assert payload["requires_exact_hash_ack"] is True
    assert payload["activation_scope"] == "sizing_only"
    assert payload["d2_thresholds_changed"] is False
    assert payload["parameter_values"]["MAX_NOTIONAL_USD"] == "100.00"
    assert payload["parameter_values"]["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"] == "0.0125"


def test_activation_requires_exact_ack(tmp_path: Path) -> None:
    _write_safe_root(tmp_path)
    write_candidate(tmp_path / "reports/backtests/sizing-only-20-100-approved-profile-candidate.json")

    report = build_activation_report(root=tmp_path, ack="", apply=True, write_env=True)

    assert report["activation_performed"] is False
    assert "exact_ack_missing" in report["blockers"]
    assert report["coinbase_action_attempted"] is False
    assert report["service_restart_performed"] is False


def test_activation_writes_profile_and_env_with_ack(tmp_path: Path, monkeypatch) -> None:
    _write_safe_root(tmp_path)
    _set_minimal_config_env(monkeypatch)
    write_candidate(tmp_path / "reports/backtests/sizing-only-20-100-approved-profile-candidate.json")

    report = build_activation_report(root=tmp_path, ack=ACK, apply=True, write_env=True)

    assert report["activation_performed"] is True
    assert report["bot_config_validation"]["status"] == "BOT_CONFIG_VALID"
    active = json.loads((tmp_path / "state/approved_parameter_profile.json").read_text())
    assert active["profile_name"] == PROFILE_NAME
    assert active["parameters"]["MAX_NOTIONAL_USD"] == "100.00"
    assert active["parameters"]["PHASE_D2_MIN_REWARD_TO_FEE_RATIO"] == "3.0"
    env_text = (tmp_path / ".env").read_text()
    assert f"APPROVED_PARAMETER_PROFILE_HASH={sha256_file(tmp_path / 'state/approved_parameter_profile.json')}" in env_text
    assert "REPLICATION_ENABLED=false" in env_text
    assert "MARKET_ORDER_ENABLED=false" in env_text
    assert report["manual_coinbase_order_action_attempted"] is False


def test_sizing_tool_writes_candidate_and_report(tmp_path: Path, monkeypatch) -> None:
    _write_safe_root(tmp_path)
    _set_minimal_config_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = sizing_main(["--ack", ACK, "--apply", "--write-env"])

    assert rc == 0
    assert (tmp_path / "reports/backtests/sizing-only-20-100-approved-profile-candidate.json").exists()
    report = json.loads((tmp_path / "reports/live_runs/sizing-only-20-100-activation-latest.json").read_text())
    assert report["activation_performed"] is True
    assert report["service_restart_performed"] is False
