from __future__ import annotations

from bot.setup_pattern_library import build_setup_pattern_matrix, build_setup_pattern_status


def test_setup_pattern_library_reports_required_patterns_without_live_authority() -> None:
    report = build_setup_pattern_status()
    matrix = build_setup_pattern_matrix()
    names = {row["setup_pattern"] for row in matrix}

    assert report["read_only"] is True
    assert report["live_order_authority"] is False
    assert report["copy_code"] is False
    assert "trend_continuation" in names
    assert "breakout_retest" in names
    assert "vwap_reclaim" in names
    assert any(row["priority"] == "P0" or row["priority"] == "P1" for row in matrix)
