from __future__ import annotations

from pathlib import Path

from tools.build_adaptive_learning_depth_sprint_audit import (
    build_adaptive_learning_depth_sprint_audit,
    render_markdown,
)


def test_audit_self_reports_no_live_side_effects(tmp_path: Path):
    report = build_adaptive_learning_depth_sprint_audit(root=tmp_path)

    assert report["read_only"] is True
    assert report["llm_call_made"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["trading_state_mutated"] is False
    assert report["open_orders_mutated"] is False
    assert report["positions_mutated"] is False
    assert report["approved_profile_mutated"] is False
    assert report["env_mutated"] is False
    assert report["new_runtime_blocker_added"] is False
    assert report["automatic_parameter_apply_enabled"] is False
    assert report["tradingbot_service_restarted"] is False
    assert report["operator_action"] == "refresh dashboard"


def test_audit_findings_are_nonempty_and_markdown_renders(tmp_path: Path):
    report = build_adaptive_learning_depth_sprint_audit(root=tmp_path)
    assert report["findings"]
    markdown = render_markdown(report)
    assert "# Adaptive Learning Depth Sprint Audit" in markdown
    assert "Operator action" in markdown
