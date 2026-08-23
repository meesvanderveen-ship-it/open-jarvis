from __future__ import annotations

import json
from pathlib import Path

from tools.write_autonomous_live_run_report import build_autonomous_live_run_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_run_report_counts_fixture_logs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(tmp_path / "state/positions.json", {})
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "cycle_summary.jsonl").write_text('{"generated_at":"2026-06-12T10:00:00+00:00","total":8,"wait":7,"close_position":1}\n', encoding="utf-8")
    (logs / "heartbeat_summary.jsonl").write_text('{"generated_at":"2026-06-12T11:00:00+00:00","total":1}\n', encoding="utf-8")
    (logs / "order_events.jsonl").write_text('{"generated_at":"2026-06-12T10:01:00+00:00","event_type":"phase_c43_live_entry_order_submitted"}\n{"generated_at":"2026-06-12T10:02:00+00:00","event_type":"phase_c43_live_entry_order_filled"}\n', encoding="utf-8")
    report = build_autonomous_live_run_report(root=tmp_path, since_hours=24)
    assert report["summary"]["cycles"] == 1
    assert report["summary"]["heartbeat_cycles"] == 1
    assert report["summary"]["orders_submitted"] == 1
    assert report["summary"]["fills"] == 1


def test_run_report_recommends_continue_mode_a_on_clean_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(tmp_path / "state/positions.json", {})
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/cycle_summary.jsonl").write_text('{"generated_at":"2026-06-12T10:00:00+00:00","total":8,"wait":7}\n', encoding="utf-8")
    report = build_autonomous_live_run_report(root=tmp_path, since_hours=24)
    assert report["run_quality"] == "good"
    assert report["recommendation"] == "continue_mode_a"


def test_run_report_recommends_stop_and_fix_on_lifecycle_exception(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(tmp_path / "state/positions.json", {})
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "errors.jsonl").write_text('{"generated_at":"2026-06-12T10:00:00+00:00","error":"lifecycle service hook failed ticker mag niet leeg zijn"}\n', encoding="utf-8")
    report = build_autonomous_live_run_report(root=tmp_path, since_hours=24)
    assert report["run_quality"] == "bad"
    assert report["recommendation"] == "stop_and_fix"
