from __future__ import annotations

import json
from pathlib import Path

import tools.prepare_autonomous_endurance_run as prepare


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _ready_report() -> dict:
    return {
        "recommendation": "ready_for_mode_a_bounded_autonomous_live_run",
        "blockers": [],
        "warnings": [],
        "mode_a_readiness": {"ready": True, "reason": "autonomous entries and D3 exits ready; stop-exit preview-only"},
        "mode_b_readiness": {"ready": False, "reason": "controlled stop-exit apply disabled and requires ACK"},
    }


def _status_report() -> dict:
    return {
        "mode": "mode_a_preview_stop_exit",
        "run_health": "healthy",
        "service_detectable": False,
        "systemd_service_status": "unknown",
        "systemd_pid": "",
        "lock_pid": "",
        "pid_consistent": True,
        "stale_lock_detected": False,
    }


def test_prepare_endurance_24h_allowed_when_mode_a_ready_mode_b_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prepare, "build_full_autonomous_run_readiness_report", lambda root: _ready_report())
    monkeypatch.setattr(prepare, "build_autonomous_live_run_status", lambda root: _status_report())
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    report = prepare.build_prepare_autonomous_endurance_run(root=tmp_path, hours=24)
    assert report["endurance_run_allowed"] is True
    assert report["mode_b_disabled_reason"] == "controlled stop-exit apply disabled and requires ACK"
    assert report["operator_commands"]["write_report"].endswith("--since-hours 24 --json-out reports/live_runs/live-run-24h.json")


def test_prepare_endurance_blocked_on_duplicate_d3(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prepare, "build_full_autonomous_run_readiness_report", lambda root: _ready_report())
    monkeypatch.setattr(prepare, "build_autonomous_live_run_status", lambda root: _status_report())
    order = {
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos1",
        "exchange_order_id": "x",
    }
    _write_json(tmp_path / "state/open_orders.json", {"orders": {"a": {**order, "client_order_id": "a"}, "b": {**order, "client_order_id": "b"}}})
    report = prepare.build_prepare_autonomous_endurance_run(root=tmp_path, hours=24)
    assert report["endurance_run_allowed"] is False
    assert "duplicate_open_d3_exit" in report["blockers"]


def test_prepare_endurance_blocked_on_missing_exchange_order_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prepare, "build_full_autonomous_run_readiness_report", lambda root: _ready_report())
    monkeypatch.setattr(prepare, "build_autonomous_live_run_status", lambda root: _status_report())
    _write_json(
        tmp_path / "state/open_orders.json",
        {
            "orders": {
                "a": {
                    "client_order_id": "a",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "status": "submitted",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "linked_position_id": "pos1",
                }
            }
        },
    )
    report = prepare.build_prepare_autonomous_endurance_run(root=tmp_path, hours=24)
    assert report["endurance_run_allowed"] is False
    assert "missing_exchange_order_id_on_open_d3_exit" in report["blockers"]
