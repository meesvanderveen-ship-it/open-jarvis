from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_report_lineage import build_phase_d6_report_lineage


def _manifest():
    return {
        "phase": "D6_report_manifest_reproducibility_index_v1",
        "status": "ready",
        "manifest_rows": [
            {
                "source_path": "/tmp/inventory.json",
                "report_type": "parameter_inventory",
                "detected_phase": "D6_parameter_inventory_v1",
                "reproducibility_status": "reproducible_metadata_present",
                "input_paths_detected": [],
            },
            {
                "source_path": "/tmp/review.json",
                "report_type": "parameter_review_pack",
                "detected_phase": "D6_parameter_review_pack_scaffold_v1",
                "reproducibility_status": "reproducible_metadata_present",
                "input_paths_detected": ["/tmp/inventory.json"],
            },
        ],
        "blockers": [],
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


def test_lineage_builds_nodes_edges_from_manifest():
    lineage = build_phase_d6_report_lineage(manifest_report=_manifest())
    assert lineage["status"] == "d6_report_lineage_ready"
    assert lineage["source_summary"]["node_count"] == 2
    assert lineage["source_summary"]["edge_count"] >= 1
    assert lineage["lineage_status"] == "complete_for_supplied_reports"
    assert not lineage["missing_input_references"]
    _assert_safe(lineage)


def test_lineage_cli_loads_manifest(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    manifest_path = _write_json(tmp_path / "research" / "manifest.json", _manifest())
    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_report_lineage.py", "--manifest", str(manifest_path), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    lineage = json.loads(result.stdout)
    assert result.stderr == ""
    assert lineage["source_summary"]["node_count"] == 2
    _assert_safe(lineage)
