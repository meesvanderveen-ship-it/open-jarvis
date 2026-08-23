from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_research_index_export import (
    build_phase_d6_research_index_export,
    research_index_export_to_markdown,
    write_research_index_export,
)


def _manifest():
    return {
        "phase": "D6_report_manifest_reproducibility_index_v1",
        "status": "ready",
        "source_summary": {"report_count": 1},
        "manifest_rows": [{"source_path": "/tmp/report.json", "report_type": "generic_research_report", "input_paths_detected": []}],
        "reproducibility_status_counts": {"reproducible_metadata_present": 1},
        "report_type_counts": {"generic_research_report": 1},
        "missing_safety_flag_counts": {},
        "blockers": [],
    }


def _lineage():
    return {
        "phase": "D6_report_lineage_dependency_graph_v1",
        "status": "ready",
        "source_summary": {"node_count": 1, "edge_count": 0},
        "lineage_status": "complete_for_supplied_reports",
        "missing_input_references": [],
        "blockers": [],
    }


def _safety():
    return {
        "phase": "D6_research_safety_validator_v1",
        "status": "ready",
        "overall_status": "pass",
        "pass_count": 1,
        "warning_count": 0,
        "blocker_count": 0,
        "missing_flag_counts": {},
        "prohibited_phrase_hits": {},
        "blockers": [],
    }


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


def test_research_index_export_combines_manifest_lineage_and_safety():
    report = build_phase_d6_research_index_export(
        manifest_report=_manifest(),
        lineage_report=_lineage(),
        safety_validation_report=_safety(),
    )
    markdown = research_index_export_to_markdown(report)

    assert report["status"] == "d6_research_index_export_ready"
    assert report["source_summary"]["safety_overall_status"] == "pass"
    assert "No parameter changes approved." in markdown
    assert "best parameter" not in markdown.lower()
    assert "change parameter" not in markdown.lower()
    assert "recommendation" not in markdown.lower()
    _assert_safe(report)


def test_research_index_export_writes_only_reports_d6_outputs(tmp_path: Path):
    report = build_phase_d6_research_index_export(
        manifest_report=_manifest(),
        lineage_report=_lineage(),
        safety_validation_report=_safety(),
    )
    json_output = tmp_path / "reports" / "d6" / "index.json"
    md_output = tmp_path / "reports" / "d6" / "index.md"
    assert write_research_index_export(report, json_output) == json_output
    assert write_research_index_export(report, md_output, markdown=True) == md_output
    with pytest.raises(ValueError, match="reports_d6"):
        write_research_index_export(report, tmp_path / "reports" / "index.json")
    with pytest.raises(ValueError, match="state"):
        write_research_index_export(report, tmp_path / "state" / "index.json")


def test_research_index_export_cli_markdown(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    manifest = _write_json(tmp_path / "research" / "manifest.json", _manifest())
    lineage = _write_json(tmp_path / "research" / "lineage.json", _lineage())
    safety = _write_json(tmp_path / "research" / "safety.json", _safety())
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_research_index_export.py",
            "--manifest",
            str(manifest),
            "--lineage",
            str(lineage),
            "--safety-validation",
            str(safety),
            "--markdown",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stderr == ""
    assert "# D.6 Research Index Export" in result.stdout
    assert "No live actions approved." in result.stdout
