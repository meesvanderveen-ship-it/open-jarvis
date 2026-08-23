from __future__ import annotations

import json
from pathlib import Path

from tools.show_autonomous_live_run_status import build_autonomous_live_run_status
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report
import tools.show_autonomous_live_run_status as status_tool


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _seed_ready(root: Path, monkeypatch) -> None:
    monkeypatch.chdir(root)
    env = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test-key",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": "true",
        "ENABLE_AUTONOMOUS_STOP_EXIT_APPLY": "false",
        "ENABLE_APPROVED_PARAMETER_PROFILE": "false",
        "MARKET_ORDER_ENABLED": "false",
        "ENABLE_MARKET_ORDERS": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "REPLICATION_ENABLED": "true",
        "REPLICA_URL": "http://100.64.0.2:8787",
        "REPLICA_SHARED_HMAC_SECRET": "test-secret",
        "REPLICATION_LIFECYCLE_ENABLED": "true",
        "REPLICATION_LIFECYCLE_HTTP_ENABLED": "true",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    (root / "bot").mkdir(parents=True, exist_ok=True)
    (root / "bot/atomic_io.py").write_text("# fixture\n", encoding="utf-8")
    (root / "bot/run_cycle_guard.py").write_text("# fixture\n", encoding="utf-8")
    _write_json(root / "state/open_orders.json", {"orders": {"d3": {"client_order_id": "d3", "exchange_order_id": "x", "order_id": "x", "ticker": "BTC-USDC", "side": "SELL", "status": "submitted", "phase": "D3_controlled_live_reduce_only_exits", "linked_position_id": "p"}}})
    _write_json(root / "state/positions.json", {"BTC-USDC": {"ticker": "BTC-USDC", "status": "open", "position_size_base": "0.1", "bot_managed_base": "0.1"}})
    (root / "logs/cycle_summary.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (root / "logs/cycle_summary.jsonl").write_text('{"generated_at":"2026-06-12T10:00:00+00:00","total":8,"wait":8,"errors":0}\n', encoding="utf-8")
    (root / "logs/loop.log").write_text(
        "Cycle summary | total=8 | errors=0 | approve_trade=0 | wait=8 | reject=0 | reduce_size=0 | close_position=0 | executed=0\n"
        "Gate summary | priority_analyze=0 | analyze=7 | watch=0 | skip=1 | fallback_hits=0\n",
        encoding="utf-8",
    )


def test_status_mode_a_ready_with_mode_b_disabled(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    report = build_autonomous_live_run_status(root=tmp_path)
    assert report["latest_readiness_recommendation"] == "ready_for_mode_a_bounded_autonomous_live_run"
    assert report["read_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["open_d3_exit_summary"]["count"] == 1
    assert report["replication_status"]["replication_enabled"] is True
    assert report["replication_status"]["replica_url_present"] is True
    assert report["replication_status"]["replica_shared_secret_present"] is True
    assert report["replication_status"]["replication_lifecycle_enabled"] is True
    assert report["replication_status"]["replication_lifecycle_http_enabled"] is True
    assert report["replication_status"]["follower_health_checked"] is False
    assert report["replication_status"]["follower_health_ok"] is None
    assert report["replication_status"]["follower_mode"] == "unknown"

    readiness = build_full_autonomous_run_readiness_report(root=tmp_path)
    assert readiness["replication_status"]["replication_enabled"] is True
    assert readiness["replication_status"]["last_lifecycle_publish_status"] == "unknown"


def test_status_critical_on_duplicate_d3(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    payload = json.loads((tmp_path / "state/open_orders.json").read_text())
    payload["orders"]["d3b"] = {**payload["orders"]["d3"], "client_order_id": "d3b", "exchange_order_id": "y", "order_id": "y"}
    _write_json(tmp_path / "state/open_orders.json", payload)
    report = build_autonomous_live_run_status(root=tmp_path)
    assert report["run_health"] == "critical"
    assert report["open_orders_summary"]["duplicate_open_d3_exit_positions"] == ["p"]


def test_status_systemd_unavailable_is_unknown_not_not_running(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    monkeypatch.setattr(status_tool, "detect_service_status", lambda: {"detectable": False, "status": "unknown", "active_pid": ""})
    report = build_autonomous_live_run_status(root=tmp_path)
    assert report["service_detectable"] is False
    assert report["mode"] != "not_running"


def test_status_detects_pid_mismatch(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    monkeypatch.setattr(status_tool, "detect_service_status", lambda: {"detectable": True, "status": "active/running", "active_pid": "999999"})
    (tmp_path / "state/run_trader_loop.lock").write_text(str(__import__("os").getpid()), encoding="utf-8")
    report = build_autonomous_live_run_status(root=tmp_path)
    assert report["pid_consistent"] is False
    assert report["run_health"] == "warning"


def test_status_does_not_report_mode_a_when_mode_b_apply_flag_lacks_ack(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    monkeypatch.setenv("ENABLE_CONTROLLED_STOP_MARKET_EXITS", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY", "true")
    monkeypatch.delenv("MODE_B_CONTROLLED_STOP_EXIT_ACK", raising=False)

    report = build_autonomous_live_run_status(root=tmp_path)

    assert report["mode"] == "mode_b_apply_enabled"
    assert report["readiness"]["mode_a_readiness"]["ready"] is False
    assert "mode_b_stop_exit_apply_ack_missing" in report["readiness"]["blockers"]
    assert report["mode_b_ack_readiness"]["ack_valid"] is False


def test_status_parses_cycle_and_gate_summary(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    report = build_autonomous_live_run_status(root=tmp_path)
    assert report["last_cycle_summary"] == {
        "total": 8,
        "errors": 0,
        "approve_trade": 0,
        "wait": 8,
        "reject": 0,
        "reduce_size": 0,
        "close_position": 0,
        "executed": 0,
    }
    assert report["last_gate_summary"] == {
        "priority_analyze": 0,
        "analyze": 7,
        "watch": 0,
        "skip": 1,
        "fallback_hits": 0,
    }
    assert report["run_health"] != "warning"
