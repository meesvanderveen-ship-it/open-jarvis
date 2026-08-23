from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_report_manifest import build_phase_d6_report_manifest


def _safe_payload(phase="D6_parameter_inventory_v1"):
    return {
        "generated_at": "2026-05-31T00:00:00Z",
        "phase": phase,
        "status": "ready",
        "source_summary": {"input_paths": ["fixtures/source.json"]},
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


def test_manifest_catalogs_reports_and_hashes(tmp_path: Path):
    report_path = _write_json(tmp_path / "reports" / "d6" / "inventory.json", _safe_payload())

    manifest = build_phase_d6_report_manifest(report_paths=[report_path])

    assert manifest["status"] == "d6_report_manifest_ready"
    assert manifest["source_summary"]["report_count"] == 1
    row = manifest["manifest_rows"][0]
    assert row["sha256"]
    assert row["detected_phase"] == "D6_parameter_inventory_v1"
    assert row["reproducibility_status"] == "reproducible_metadata_present"
    assert row["missing_safety_flags"] == []
    _assert_safe(manifest)


def test_manifest_treats_source_paths_as_hashable_inputs(tmp_path: Path):
    source = tmp_path / "research" / "source.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"source": true}', encoding="utf-8")
    payload = _safe_payload("D6_report_bundle_writer_atomic_output_v1")
    payload["report_type"] = "d6_live_test_readiness"
    payload["source_paths"] = [str(source)]
    report_path = _write_json(tmp_path / "reports" / "d6" / "bundle.json", payload)

    manifest = build_phase_d6_report_manifest(report_paths=[report_path])

    row = manifest["manifest_rows"][0]
    assert row["report_type"] == "d6_live_test_readiness"
    assert str(source) in row["input_paths_detected"]
    assert row["reproducibility_status"] == "reproducible_metadata_present"


def test_manifest_scans_reports_d6_directory_and_refuses_state(tmp_path: Path):
    report_path = _write_json(tmp_path / "reports" / "d6" / "pack.json", _safe_payload("D6_parameter_review_pack_scaffold_v1"))
    manifest = build_phase_d6_report_manifest(report_directories=[report_path.parent])
    assert manifest["source_summary"]["report_count"] == 1

    state_path = _write_json(tmp_path / "state" / "report.json", _safe_payload())
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_report_manifest(report_paths=[state_path])


def test_manifest_cli_stdout_only(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    report_path = _write_json(tmp_path / "reports" / "d6" / "inventory.json", _safe_payload())

    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_report_manifest.py", "--report", str(report_path), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    manifest = json.loads(result.stdout)
    assert result.stderr == ""
    assert manifest["source_summary"]["report_count"] == 1
    _assert_safe(manifest)
