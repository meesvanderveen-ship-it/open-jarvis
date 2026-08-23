from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_governance_evidence_bundle import (
    build_phase_d6_governance_evidence_bundle,
    parse_function_preservation_audit,
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


def _audit_text() -> str:
    return """Function preservation audit
===========================
Status:    ok_observe_only

Order store:
  total_records=14 total_open_orders=0 open_c43_entry=0 open_d3_exit=0

Warnings:
  - sample_warning

Next steps:
  - local only
"""


def test_parse_function_preservation_audit_extracts_status_counts_and_warnings():
    parsed = parse_function_preservation_audit(_audit_text())
    assert parsed["status"] == "ok_observe_only"
    assert parsed["total_open_orders"] == 0
    assert parsed["open_d3_exit"] == 0
    assert parsed["warning_count"] == 1


def test_governance_bundle_summarizes_local_safety_and_evidence(tmp_path: Path):
    evidence = tmp_path / "logs" / "order_events.jsonl"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "event_type": "d3_live_exit_reconciled",
                "ticker": "BTC-USDC",
                "client_order_id": "example-TP1",
                "status": "filled",
                "filled_quote": "4.80",
                "fee_quote": "0.02",
                "post_only": True,
                "is_complete_lifecycle_event": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = build_phase_d6_governance_evidence_bundle(
        open_orders_report={"summary": {"open_orders": 0, "total_orders": 1}},
        function_audit_text=_audit_text(),
        d3_controlled_exits_report={
            "status": "d3_no_manageable_open_position",
            "live_order_submitted": False,
            "live_submission_attempted": False,
            "position_present": False,
            "open_d3_exit_orders": {"total_open_d3_exit_orders": 0},
            "reservation_governance": {"reserved_base_open_exit_orders": "0", "blockers": []},
        },
        state_hashes_before={"state/open_orders.json": "a", "state/positions.json": "b"},
        state_hashes_after={"state/open_orders.json": "a", "state/positions.json": "b"},
        evidence_input_paths=[evidence],
        environment_summary={"bwrap_on_path": False},
    )

    assert report["overall_status"] == "pass"
    assert report["local_lifecycle_safety"]["state_hashes_match"] is True
    assert report["historical_evidence_summary"]["evidence_row_count"] >= 1
    assert "tiny_notional_lifecycle_overhead" in report["historical_evidence_summary"]["evidence_category_counts"]
    _assert_safe(report)


def test_governance_bundle_cli_stdout_is_safe():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tools/build_phase_d6_governance_evidence_bundle.py"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert result.stderr == ""
    assert payload["report_type"] == "d6_governance_evidence_bundle"
    assert payload["content"]["overall_status"] == "pass"
    _assert_safe(payload)
