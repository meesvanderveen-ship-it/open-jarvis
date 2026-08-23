import json
from pathlib import Path

from bot.phase_d6_backlearning_multisource_v6 import (
    build_backlearning_multisource_scaffold_v6,
    build_open_source_backlearning_pattern_map_v4,
)


def test_pattern_map_v4_is_pattern_only() -> None:
    report = build_open_source_backlearning_pattern_map_v4()

    assert report["status"] == "open_source_backlearning_pattern_map_v4_ready"
    assert "dependency_install" in report["rejected_actions"]
    assert report["learning_to_execution_enabled"] is False


def test_backlearning_v6_blocks_normal_when_primary_quality_poor(tmp_path: Path) -> None:
    source = tmp_path / "btc1h.json"
    source.write_text(json.dumps([{"start": 1}]), encoding="utf-8")

    report = build_backlearning_multisource_scaffold_v6(
        quality_summary={"global_counters": {"good_count": 1, "warning_count": 53, "poor_count": 2, "invalid_count": 0}},
        controller_result={"status": "btc_1h_staged_controller_result_ready"},
        binance_reference={"available_reference_count": 2},
        source_paths=[source],
    )

    normal_rows = [row for row in report["quality_gate_matrix"] if row["case"] == "primary_poor"]
    secondary_rows = [row for row in report["quality_gate_matrix"] if row["case"] == "secondary_reference_available"]
    assert normal_rows[0]["normal_blocked"] is True
    assert secondary_rows[0]["condition_met"] is True
    assert report["dataset_contracts"]["secondary"]["may_fill_primary_cache"] is False
    assert report["normal_backtest_released_from_secondary_source"] is False
    assert report["dataset_provenance_hashes"][0]["sha256"]
