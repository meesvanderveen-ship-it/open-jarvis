import json
from pathlib import Path

from bot.phase_d6_known_gap_decision_tool import build_known_gap_decision


def _write(path: Path, rows_or_content):
    path.write_text(json.dumps(rows_or_content), encoding="utf-8")
    return path


def test_known_gap_decision_classifies_adjusted_missing_as_coinbase_hole_candidate(tmp_path: Path) -> None:
    existing = _write(tmp_path / "existing.json", [])
    failed = _write(tmp_path / "failed.json", [{"start": 0, "product_id": "BTC-USDC", "timeframe": "1H"}])
    adjusted = _write(
        tmp_path / "adjusted.json",
        {
            "content": {
                "status": "btc_1h_chunk52_adjusted_fetch_result_v1_blocked",
                "candidate_validation": {"missing_expected_count": 5, "unexpected_starts_sample": [3600]},
            }
        },
    )

    report = build_known_gap_decision(
        chunk_id="BTCUSDC-1H-gap01:chunk52",
        expected_start=0,
        expected_end_exclusive=3600 * 2,
        existing_path=existing,
        failed_candidate_path=failed,
        adjusted_result_path=adjusted,
    )

    assert report["classification"] == "confirmed_coinbase_data_hole_candidate"
    assert report["merge_allowed"] is False
    assert report["binance_repair_allowed"] is False
