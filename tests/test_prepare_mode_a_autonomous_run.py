from __future__ import annotations

import json
from pathlib import Path

from tests.test_autonomous_live_run_status import _seed_ready
from tools.prepare_mode_a_autonomous_run import build_prepare_mode_a_autonomous_run


def test_prepare_mode_a_outputs_operator_commands(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    report = build_prepare_mode_a_autonomous_run(root=tmp_path)
    assert report["mode_a_start_allowed"] is True
    assert "systemctl restart coinbase-bot.service" in report["operator_command_restart"]
    assert "show_autonomous_live_run_status.py --json" in report["operator_command_monitor"]
    assert report["service_restart_attempted"] is False


def test_prepare_mode_a_blocks_duplicate_d3(tmp_path: Path, monkeypatch) -> None:
    _seed_ready(tmp_path, monkeypatch)
    payload = json.loads((tmp_path / "state/open_orders.json").read_text())
    payload["orders"]["d3b"] = {**payload["orders"]["d3"], "client_order_id": "d3b", "exchange_order_id": "y", "order_id": "y"}
    (tmp_path / "state/open_orders.json").write_text(json.dumps(payload), encoding="utf-8")
    report = build_prepare_mode_a_autonomous_run(root=tmp_path)
    assert report["mode_a_start_allowed"] is False
    assert "duplicate_open_d3_exit" in report["blockers"]
