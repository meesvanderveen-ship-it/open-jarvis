from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_research_safety_validator import build_phase_d6_research_safety_validation_report


def _safe_payload():
    return {
        "phase": "D6_safe_report_v1",
        "status": "ready",
        "source_summary": {"source": "fixture"},
        "warnings": [],
        "blockers": [],
        "research_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "no_optimization": True,
        "parameter_search_performed": False,
        "parameter_change_allowed": False,
        "learning_to_execution_allowed": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "human_review_required": True,
        "parameter_review_approved": False,
    }


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def test_safety_validator_passes_safe_report_and_blocks_phrase(tmp_path: Path):
    safe = _write_json(tmp_path / "research" / "safe.json", _safe_payload())
    unsafe_payload = _safe_payload()
    unsafe_payload["notes"] = "execute this trade"
    unsafe = _write_json(tmp_path / "research" / "unsafe.json", unsafe_payload)

    report = build_phase_d6_research_safety_validation_report(report_paths=[safe, unsafe])

    assert report["pass_count"] == 1
    assert report["overall_status"] == "blocked"
    assert report["prohibited_phrase_hits"]["execute this trade"] == 1
    _assert_safe(report)


def test_safety_validator_cli(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    safe = _write_json(tmp_path / "research" / "safe.json", _safe_payload())
    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_research_safety_validator.py", "--report", str(safe), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["overall_status"] == "pass"
    _assert_safe(report)
