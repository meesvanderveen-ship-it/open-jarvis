from __future__ import annotations

from bot.phase_d6_remaining_work_planner import build_backlearning_review_package


def test_backlearning_review_package_blocks_parameter_review_and_learning_bridge():
    report = build_backlearning_review_package(scaffold={"content": {"summary": {"all_parameter_reviews_blocked": True}}}, guardrails={"content": {"summary": {}}})
    assert "oos_holdout_labels" in report["required_evidence_before_parameter_review"]
    assert report["explicit_blockers"]["parameter_review_approved"] is False
    assert report["explicit_blockers"]["parameter_values_changed"] is False
    assert report["explicit_blockers"]["optimization_performed"] is False
    assert report["explicit_blockers"]["learning_to_execution_enabled"] is False
    assert report["contains_recommendations"] is False
