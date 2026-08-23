from __future__ import annotations

from bot.phase_d6_remaining_work_planner import build_backtest_execution_package


def test_backtest_execution_package_lists_commands_without_optimization_or_ranking():
    report = build_backtest_execution_package(readiness_matrix={"content": {"rows": [{"ticker": "BTC-USDC"}]}})
    assert len(report["rows"]) == 3
    assert "show_phase_d6_dataset_quality.py" in report["rows"][0]["dataset_quality_command"]
    assert report["rows"][0]["no_optimization"] is True
    assert report["rows"][0]["ranking_performed"] is False
    assert report["blocked_until_data_exists"] is True
    assert report["parameter_review_approved"] is False
