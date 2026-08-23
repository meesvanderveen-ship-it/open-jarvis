import json
from pathlib import Path

from bot.phase_d6_backlearning_multisource_v7 import (
    build_backlearning_multisource_scaffold_v7,
    build_open_source_backlearning_pattern_map_v5,
)


def test_pattern_map_v5_adds_cross_source_visibility() -> None:
    report = build_open_source_backlearning_pattern_map_v5()

    assert report["report_name"] == "open_source_backlearning_pattern_map_v5"
    assert "cross_source_reference_visibility" in report["v5_additions"]
    assert report["learning_to_execution_enabled"] is False


def test_scaffold_v7_keeps_exploratory_separate_from_normal(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps([{"start": 1}]), encoding="utf-8")

    report = build_backlearning_multisource_scaffold_v7(
        quality_summary={"global_counters": {"good_count": 1, "warning_count": 53, "poor_count": 2, "invalid_count": 0}},
        controller_result={"status": "btc_1h_staged_controller_result_v2_ready"},
        binance_reference={"available_reference_count": 3},
        source_paths=[source],
    )

    assert report["report_name"] == "backlearning_multisource_scaffold_v7"
    assert report["normal_vs_exploratory_gate"]["normal_backtests_require_primary_coinbase_quality"] is True
    assert report["normal_vs_exploratory_gate"]["exploratory_only_creates_parameter_evidence"] is False
    assert report["cross_source_reference_visibility"]["reference_only"] is True
    assert report["learning_to_execution_enabled"] is False
