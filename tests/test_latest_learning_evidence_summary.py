from __future__ import annotations

import json
from pathlib import Path

from tools.build_latest_learning_evidence_summary import (
    build_latest_learning_evidence_summary,
    write_reports,
)


def _write_decision_outcomes(root: Path, records: list[dict]) -> None:
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "decision_outcomes.json").write_text(json.dumps({"records": records}), encoding="utf-8")


def _record(*, ticker: str, decision_category: str, outcome_label: str, confidence: float = 58.0) -> dict:
    return {
        "ticker": ticker,
        "created_at": "2026-06-01T00:00:00Z",
        "status": "resolved",
        "decision_category": decision_category,
        "growbot_river_learning_context": {"regime": "unknown", "state": {"confidence": confidence}},
        "outcome": {"outcome_label": outcome_label, "price_change_pct": 0.02},
    }


def test_first_run_has_no_previous_snapshot_and_flags_new_signals(tmp_path: Path):
    records = [
        _record(ticker=f"T{i}", decision_category="wait", outcome_label="missed_opportunity")
        for i in range(9)
    ]
    _write_decision_outcomes(tmp_path, records)

    report, snapshot = build_latest_learning_evidence_summary(root=tmp_path)

    assert report["read_only"] is True
    assert report["llm_call_made"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert any("pressure increased" in line for line in report["learning_evidence_summary"])
    assert "JUDGE_MIN_GATE_CONFIDENCE" in snapshot["parameters"]


def test_second_run_with_unchanged_data_has_no_deltas(tmp_path: Path):
    records = [
        _record(ticker=f"T{i}", decision_category="wait", outcome_label="missed_opportunity")
        for i in range(9)
    ]
    _write_decision_outcomes(tmp_path, records)

    report1, snapshot1 = build_latest_learning_evidence_summary(root=tmp_path)
    write_reports(report1, snapshot1, root=tmp_path)

    report2, _ = build_latest_learning_evidence_summary(root=tmp_path)

    assert report2["parameter_pressure_deltas"] == []
    assert "No parameter pressure changes detected since the last check." in report2["learning_evidence_summary"]


def test_write_reports_persists_json_md_and_snapshot(tmp_path: Path):
    _write_decision_outcomes(tmp_path, [])
    report, snapshot = build_latest_learning_evidence_summary(root=tmp_path)
    write_reports(report, snapshot, root=tmp_path)

    json_path = tmp_path / "reports" / "learning" / "learning-evidence-summary-latest.json"
    md_path = tmp_path / "reports" / "learning" / "learning-evidence-summary-latest.md"
    snapshot_path = tmp_path / "reports" / "learning" / ".learning-evidence-snapshot.json"
    assert json_path.exists()
    assert md_path.exists()
    assert snapshot_path.exists()
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == snapshot
