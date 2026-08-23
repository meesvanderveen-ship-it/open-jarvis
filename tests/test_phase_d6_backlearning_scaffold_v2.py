from bot.phase_d6_backlearning_scaffold_v2 import (
    build_backlearning_scaffold_v2,
    build_open_source_backlearning_architecture_v2,
)


def test_open_source_architecture_is_pattern_only_and_safety_gated() -> None:
    report = build_open_source_backlearning_architecture_v2()

    assert report["status"] == "open_source_backlearning_architecture_v2_ready"
    assert "dependency_install" in report["rejected_actions"]
    assert report["parameter_review_approved"] is False
    assert report["learning_to_execution_enabled"] is False


def test_backlearning_scaffold_blocks_when_quality_not_ready() -> None:
    report = build_backlearning_scaffold_v2(
        quality_summary={"quality_report_count": 54, "good_count": 1, "warning_count": 53, "invalid_count": 0}
    )

    assert report["dataset_quality_gate"]["normal_backtests_allowed"] is False
    assert "dataset_quality_not_ready_for_normal_backtests" in report["blockers"]
    assert report["parameter_candidate_registry"]["parameter_search_performed"] is False
    assert report["human_review_gate"]["learning_to_execution_enabled"] is False

