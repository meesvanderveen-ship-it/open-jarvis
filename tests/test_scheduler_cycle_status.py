from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tools.show_scheduler_cycle_status import build_scheduler_cycle_status, main


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_scheduler_cycle_status_reports_boundaries_and_rows(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "logs/loop.log").write_text(
        "\n".join(
            [
                "2026-06-16 12:37:38,595 - WARNING - Skipping duplicate full cycle boundary at 2026-06-16T12:00:00+00:00",
                "2026-06-16 20:00:00,004 - INFO - Starting new FULL trading cycle | allowed_tickers=BTC-USDC | ranking_enabled=True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "state/run_trader_loop_cycles.json").write_text(
        json.dumps({"last_boundary_key": "full:2026-06-16T20:00:00+00:00", "updated_at": "2026-06-16T20:00:00+00:00"}),
        encoding="utf-8",
    )
    _append(tmp_path / "logs/cycle_summary.jsonl", {"generated_at": "2026-06-16T12:08:22Z", "total": 8})
    _append(tmp_path / "logs/heartbeat_summary.jsonl", {"generated_at": "2026-06-16T19:00:00Z", "total": 0})
    _append(tmp_path / "logs/analysis.jsonl", {"generated_at": "2026-06-16T20:01:00Z", "ticker": "BTC-USDC"})

    report = build_scheduler_cycle_status(
        root=tmp_path,
        now=datetime(2026, 6, 16, 20, 5, tzinfo=timezone.utc),
    )

    assert report["last_full_cycle_boundary"] == "2026-06-16T20:00:00+00:00"
    assert report["last_full_cycle_started_at"] == "2026-06-16T20:00:00Z"
    assert report["last_full_cycle_completed_at"] == "2026-06-16T12:08:22Z"
    assert report["last_heartbeat_at"] == "2026-06-16T19:00:00Z"
    assert report["next_full_cycle_boundary"] == "2026-06-17T00:00:00Z"
    assert report["full_cycle_recently_skipped"] is False
    assert report["decision_rows_since_last_full_cycle"] == 1
    assert report["audit_data_available"] is True
    assert report["read_only"] is True


def test_scheduler_cycle_status_main_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "reports/audits/scheduler.json"
    assert main(["--root", str(tmp_path), "--json-out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["read_only"] is True
    assert "next_full_cycle_boundary" in payload
