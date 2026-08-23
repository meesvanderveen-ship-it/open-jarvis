import json
from pathlib import Path

from bot.phase_d6_backlearning_multisource_v8 import (
    build_backlearning_multisource_scaffold_v8,
    build_open_source_backlearning_pattern_map_v6,
)


def test_pattern_map_v6_records_fail_closed_accounting() -> None:
    report = build_open_source_backlearning_pattern_map_v6()

    assert report["report_name"] == "open_source_backlearning_pattern_map_v6"
    assert "fail_closed_fetch_accounting" in report["v6_additions"]
    assert report["learning_to_execution_enabled"] is False


def test_scaffold_v8_keeps_reference_unavailable_from_mutating_primary(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps([{"start": 1}]), encoding="utf-8")

    report = build_backlearning_multisource_scaffold_v8(
        quality_summary={"global_counters": {"good_count": 1, "warning_count": 53, "poor_count": 2, "invalid_count": 0}},
        controller_result={"status": "btc_1h_staged_controller_result_v3_ready"},
        binance_reference={"available_reference_count": 0},
        source_paths=[source],
    )

    assert report["report_name"] == "backlearning_multisource_scaffold_v8"
    assert report["fetch_failure_accounting"]["reference_unavailable_does_not_mutate_primary_data"] is True
    assert report["normal_vs_exploratory_gate"]["exploratory_only_creates_parameter_evidence"] is False
    assert report["learning_to_execution_enabled"] is False
