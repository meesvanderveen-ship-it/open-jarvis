from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_guardrail_summary_adapter import build_phase_d6_guardrail_summary_report


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


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_guardrail_summary_adapts_dataset_and_overfitting_reports(tmp_path: Path):
    dataset = {
        "phase": "D6_dataset_quality_aggregate_v1",
        "status": "d6_dataset_quality_aggregate_ready",
        "summary": {
            "aggregate_quality_class": "usable_with_warnings",
            "warning_counts": {"candle_gaps_detected": 1},
            "blockers": [],
        },
        "warnings": ["research_dataset_quality_aggregate_only"],
        "research_only": True,
    }
    overfitting = {
        "phase": "D6_overfitting_trial_accounting_guardrails_v1",
        "status": "d6_overfitting_guardrails_ready",
        "guardrail_class": "insufficient_for_parameter_review",
        "guardrail_warnings": ["limited_file_or_ticker_breadth"],
        "blockers": ["source_contains_rankings_blocked"],
        "research_only": True,
    }

    report = build_phase_d6_guardrail_summary_report(reports=[dataset, overfitting])

    assert report["status"] == "d6_guardrail_summary_ready"
    assert report["source_summary"]["report_count"] == 2
    assert report["guardrail_status_counts"]["warning"] == 1
    assert report["guardrail_status_counts"]["blocked"] == 1
    assert report["implicated_parameter_category_counts"]["market_data_features"] == 1
    assert report["implicated_parameter_category_counts"]["ai_prompt_judge"] == 1
    assert "source_contains_rankings_blocked" in report["blocker_counts"]
    _assert_safe(report)


def test_guardrail_summary_refuses_state_paths(tmp_path: Path):
    path = _write_json(tmp_path / "state" / "guardrail.json", {"phase": "x"})
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_guardrail_summary_report(report_paths=[path])


def test_guardrail_summary_cli_stdout_only(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    path = _write_json(
        tmp_path / "research" / "guardrail.json",
        {"phase": "D6_out_of_sample_degradation_checks_v1", "status": "ready", "warnings": ["mild_degradation"], "research_only": True},
    )

    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_guardrail_summary_adapter.py", "--report", str(path), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["guardrail_summary_rows"][0]["guardrail_type"] == "oos_degradation"
    _assert_safe(report)
