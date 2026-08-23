import json
from pathlib import Path

from bot.phase_d6_historical_gap_validator import validate_historical_gap


def _write(path: Path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_gap_validator_detects_missing_overlap_and_unexpected(tmp_path: Path) -> None:
    existing = _write(tmp_path / "existing.json", [{"start": 0, "product_id": "BTC-USDC", "timeframe": "1H"}])
    candidate = _write(
        tmp_path / "candidate.json",
        [
            {"start": 0, "product_id": "BTC-USDC", "timeframe": "1H"},
            {"start": 3600, "product_id": "BTC-USDC", "timeframe": "1H"},
            {"start": 10800, "product_id": "BTC-USDC", "timeframe": "1H"},
        ],
    )

    report = validate_historical_gap(
        candidate_path=candidate,
        existing_path=existing,
        product_id="BTC-USDC",
        timeframe="1H",
        expected_start=3600,
        expected_end_exclusive=10800,
    )

    assert report["status"] == "historical_gap_validation_blocked"
    assert report["missing_count"] == 1
    assert report["overlap_count"] == 1
    assert report["unexpected_count"] == 2
    assert report["blocks_merge"] is True
