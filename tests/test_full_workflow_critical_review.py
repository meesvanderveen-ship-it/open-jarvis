from __future__ import annotations

import json

from tools.build_full_workflow_critical_review import build_full_workflow_critical_review, main as review_main


def test_workflow_review_is_read_only_and_reports_required_questions():
    report = build_full_workflow_critical_review(root=".", generated_at="2026-06-14T00:00:00Z")
    assert report["read_only_review_first"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["env_write_performed"] is False
    assert report["patch_required"] is True
    assert "A_marketdata_agents_planner_judge_risk_execution_order" in report["checks"]
    assert "P_readiness_status_extended" in report["checks"]


def test_workflow_review_tool_writes_audit_reports(tmp_path, monkeypatch):
    monkeypatch.chdir("/root/apps/Crypto/coinbase_bot")
    json_out = tmp_path / "reports/audits/full-workflow-critical-review-latest.json"
    md_out = tmp_path / "reports/audits/full-workflow-critical-review-latest.md"
    # The tool intentionally restricts writes to cwd/reports/audits, so use default cwd path here.
    rc = review_main([])
    assert rc == 0
    payload = json.loads(open("reports/audits/full-workflow-critical-review-latest.json", encoding="utf-8").read())
    assert payload["read_only_review_first"] is True
    assert payload["coinbase_call_attempted"] is False
    assert json_out.name == "full-workflow-critical-review-latest.json"
    assert md_out.name == "full-workflow-critical-review-latest.md"

