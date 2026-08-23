from bot.phase_d6_backlearning_scaffold_v4 import (
    build_backlearning_scaffold_v4,
    build_open_source_backlearning_pattern_map_v3,
)


def test_pattern_map_v3_is_pattern_only() -> None:
    report = build_open_source_backlearning_pattern_map_v3()

    assert report["status"] == "open_source_backlearning_pattern_map_v3_ready"
    assert "dependency_install" in report["rejected_actions"]
    assert report["learning_to_execution_enabled"] is False


def test_backlearning_v4_allows_only_exploratory_when_known_gap_preview_ok() -> None:
    report = build_backlearning_scaffold_v4(
        quality_summary={"quality_report_count": 54, "good_count": 1, "warning_count": 53, "invalid_count": 0},
        known_gap_preview={
            "status": "btc_4h_known_gap_preview_ready",
            "gap_class": "acceptable_known_gap_for_exploratory_research",
        },
    )

    assert report["quality_to_backtest_gate"]["exploratory_only_allowed"] is True
    assert report["quality_to_backtest_gate"]["normal_backtest_allowed"] is False
    assert report["parameter_candidate_registry"]["runtime_mutation_allowed"] is False
    assert report["execution_gate"]["learning_to_execution_enabled"] is False
