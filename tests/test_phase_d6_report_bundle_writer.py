from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_report_bundle_writer import (
    build_phase_d6_report_bundle,
    metadata_sidecar_path,
    write_phase_d6_report_bundle,
)


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


def test_report_bundle_writer_rejects_state_and_env_paths(tmp_path: Path):
    report = build_phase_d6_report_bundle(report_type="unit", content={"ok": True})
    with pytest.raises(ValueError, match="state"):
        write_phase_d6_report_bundle(report, tmp_path / "state" / "bad.json")
    with pytest.raises(ValueError, match="env"):
        write_phase_d6_report_bundle(report, tmp_path / "reports" / "d6" / ".env")
    with pytest.raises(ValueError, match="reports_d6"):
        write_phase_d6_report_bundle(report, tmp_path / "reports" / "bad.json")


def test_report_bundle_writer_atomic_write_and_metadata_sidecar(tmp_path: Path):
    source = tmp_path / "research" / "source.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"source": true}', encoding="utf-8")
    output = tmp_path / "reports" / "d6" / "bundle.json"
    report = build_phase_d6_report_bundle(report_type="unit", content={"ok": True}, source_paths=[source])

    result = write_phase_d6_report_bundle(report, output, metadata_sidecar=True)

    assert result["status"] == "d6_report_bundle_written"
    assert output.exists()
    sidecar = metadata_sidecar_path(output)
    assert sidecar.exists()
    loaded = json.loads(output.read_text(encoding="utf-8"))
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert loaded["report_type"] == "unit"
    assert metadata["sha256"] == result["report_sha256"]
    assert str(source) in loaded["source_paths"]
    _assert_safe(loaded)
    _assert_safe(metadata)
    _assert_safe(result)


def test_report_bundle_writer_dry_run_performs_no_write(tmp_path: Path):
    output = tmp_path / "reports" / "d6" / "bundle.json"
    report = build_phase_d6_report_bundle(report_type="unit", content={"ok": True})

    result = write_phase_d6_report_bundle(report, output, metadata_sidecar=True, dry_run=True)

    assert result["status"] == "d6_report_bundle_write_preview"
    assert not output.exists()
    assert not metadata_sidecar_path(output).exists()
    _assert_safe(result)


def test_report_bundle_writer_cli_dry_run_and_markdown_are_safe(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path / "reports" / "d6" / "bundle.md"

    result = subprocess.run(
        [
            sys.executable,
            "tools/write_phase_d6_report_bundle.py",
            "--report-type",
            "unit",
            "--output",
            str(output),
            "--markdown",
            "--metadata-sidecar",
            "--dry-run",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    preview = json.loads(result.stdout)
    assert result.stderr == ""
    assert preview["dry_run"] is True
    assert not output.exists()
    prohibited = ["best" + " parameter", "change" + " parameter", "execute" + " this trade"]
    assert not any(phrase in result.stdout.lower() for phrase in prohibited)
    _assert_safe(preview)
