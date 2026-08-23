from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_final_readiness_packet import build_phase_d6_final_readiness_packet


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


def _readiness_report() -> dict:
    gates = [
        {"gate_id": "gate_0", "name": "live_lifecycle_parked", "status": "pass", "evidence": {}, "remaining_work": []},
        {"gate_id": "gate_1", "name": "state_hygiene_understood", "status": "warning", "evidence": {}, "remaining_work": []},
        {"gate_id": "gate_2", "name": "regression_readiness", "status": "pass", "evidence": {}, "remaining_work": []},
        {"gate_id": "gate_3", "name": "research_report_governance", "status": "pass", "evidence": {}, "remaining_work": []},
        {"gate_id": "gate_4", "name": "environment_hygiene", "status": "warning", "evidence": {}, "remaining_work": []},
        {
            "gate_id": "gate_5",
            "name": "future_live_test_design",
            "status": "blocked_until_exact_ack",
            "evidence": {},
            "remaining_work": [],
            "ack_required": True,
        },
    ]
    return {
        "content": {
            "overall_status": "readiness_plan_ready_future_live_test_requires_exact_ack",
            "current_state": {
                "state_hashes_match": True,
                "readiness_regression_summary": {"status": "pass", "tests_passed": 151},
            },
            "readiness_gates": gates,
        }
    }


def test_final_readiness_packet_consolidates_gates_and_boundaries():
    packet = build_phase_d6_final_readiness_packet(
        readiness_report=_readiness_report(),
        governance_evidence_report={
            "content": {
                "overall_status": "pass",
                "historical_evidence_summary": {"evidence_row_count": 112},
            }
        },
        readiness_index_report={"status": "d6_research_index_export_ready", "safety_validation_summary": {"overall_status": "pass"}},
        regression_summary={"status": "pass", "tests_passed": 151},
        state_hashes_before={"state/open_orders.json": "a", "state/positions.json": "b"},
        state_hashes_after={"state/open_orders.json": "a", "state/positions.json": "b"},
        environment_summary={"bwrap_on_path": False},
        source_report_paths=["reports/d6/live-test-readiness-20260601.json"],
    )

    assert packet["final_status"] == "ready_for_future_prompt_review_ack_required"
    assert packet["readiness_gate_summary"]["gate_status_counts"]["pass"] == 3
    assert packet["remaining_readiness_work"]["warning_disposition"]["gate_1_state_hygiene"][
        "does_block_future_prompt_review"
    ] is False
    assert "future_live_test_exact_ack_missing" in packet["blockers"]
    _assert_safe(packet)


def test_final_readiness_packet_cli_stdout_is_safe():
    repo = Path(__file__).resolve().parents[1]
    readiness = repo / "reports/d6/live-test-readiness-20260601.json"
    if not readiness.exists():
        return
    args = [
        sys.executable,
        "tools/build_phase_d6_final_readiness_packet.py",
        "--readiness-report",
        str(readiness),
        "--readiness-regression-status",
        "pass",
        "--readiness-regression-tests-passed",
        "151",
    ]
    governance = repo / "reports/d6/governance-evidence-bundle-20260601.json"
    if governance.exists():
        args.extend(["--governance-evidence-report", str(governance)])
    index = repo / "reports/d6/live-test-readiness-index-20260601.json"
    if index.exists():
        args.extend(["--readiness-index-report", str(index)])

    result = subprocess.run(args, cwd=repo, text=True, capture_output=True, check=True)

    payload = json.loads(result.stdout)
    assert result.stderr == ""
    assert payload["report_type"] == "d6_final_readiness_packet"
    assert payload["content"]["chosen_route"]["route"] == "F_combined_final_packet_regression_preflight"
    _assert_safe(payload)
