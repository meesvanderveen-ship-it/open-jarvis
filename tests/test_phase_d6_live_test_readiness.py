from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_live_test_readiness import build_phase_d6_live_test_readiness_report


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


def _audit_text() -> str:
    return """Function preservation audit
===========================
Status:    ok_observe_only

Order store:
  total_records=14 total_open_orders=0 open_c43_entry=0 open_d3_exit=0
"""


def _d3_report() -> dict:
    return {
        "status": "d3_no_manageable_open_position",
        "live_order_submitted": False,
        "live_submission_attempted": False,
        "position_present": False,
        "open_d3_exit_orders": {"total_open_d3_exit_orders": 0},
        "reservation_governance": {"reserved_base_open_exit_orders": "0", "blockers": []},
    }


def _governance_bundle() -> dict:
    return {
        "content": {
            "overall_status": "pass",
            "historical_evidence_summary": {
                "evidence_row_count": 112,
                "evidence_category_counts": {"tiny_notional_lifecycle_overhead": 2},
                "blockers": [],
            },
        }
    }


def test_live_test_readiness_report_builds_gates_and_ack_boundary():
    report = build_phase_d6_live_test_readiness_report(
        open_orders_report={"summary": {"open_orders": 0, "total_orders": 0}},
        function_audit_text=_audit_text(),
        d3_controlled_exits_report=_d3_report(),
        state_hashes_before={"state/open_orders.json": "a", "state/positions.json": "b"},
        state_hashes_after={"state/open_orders.json": "a", "state/positions.json": "b"},
        governance_bundle_report=_governance_bundle(),
        environment_summary={"bwrap_on_path": False, "bwrap_path": None},
        regression_summary={"status": "pass", "tests_passed": 151, "command": ".venv/bin/python -m pytest ..."},
    )

    gates = {gate["gate_id"]: gate for gate in report["readiness_gates"]}
    assert gates["gate_0"]["status"] == "pass"
    assert gates["gate_1"]["status"] == "warning"
    assert gates["gate_2"]["status"] == "pass"
    assert gates["gate_4"]["status"] == "warning"
    assert gates["gate_5"]["status"] == "blocked_until_exact_ack"
    assert report["overall_status"] == "readiness_plan_ready_future_live_test_requires_exact_ack"
    assert report["chosen_route"]["route"] == "F_combined_readiness_harness_preflight_evidence"
    assert report["current_state"]["state_hashes_match"] is True
    _assert_safe(report)


def test_live_test_readiness_report_blocks_if_local_lifecycle_not_parked():
    d3 = _d3_report()
    d3["open_d3_exit_orders"] = {"total_open_d3_exit_orders": 1}
    report = build_phase_d6_live_test_readiness_report(
        open_orders_report={"summary": {"open_orders": 1, "total_orders": 1}},
        function_audit_text=_audit_text().replace("total_open_orders=0", "total_open_orders=1").replace(
            "open_d3_exit=0", "open_d3_exit=1"
        ),
        d3_controlled_exits_report=d3,
        state_hashes_before={"state/open_orders.json": "a"},
        state_hashes_after={"state/open_orders.json": "a"},
        governance_bundle_report=_governance_bundle(),
        environment_summary={"bwrap_on_path": True},
    )

    gates = {gate["gate_id"]: gate for gate in report["readiness_gates"]}
    assert gates["gate_0"]["status"] == "blocked"
    assert report["overall_status"] == "blocked_local_safety_issue"


def test_live_test_readiness_cli_stdout_is_safe():
    repo = Path(__file__).resolve().parents[1]
    args = [sys.executable, "tools/build_phase_d6_live_test_readiness_report.py"]
    governance = repo / "reports/d6/governance-evidence-bundle-20260601.json"
    if governance.exists():
        args.extend(["--governance-bundle", str(governance)])
    result = subprocess.run(
        args,
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert result.stderr == ""
    assert payload["report_type"] == "d6_live_test_readiness"
    assert payload["content"]["readiness_gates"][0]["gate_id"] == "gate_0"
    _assert_safe(payload)
