import json

from bot.phase_d6_candidate_coverage_validator import filter_candidate_to_gap, validate_candidate_coverage


def _row(start: int, product: str = "BTC-USDC", timeframe: str = "1D") -> dict:
    return {
        "product_id": product,
        "timeframe": timeframe,
        "start": start,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "volume": "1",
    }


def test_candidate_validator_passes_exact_gap(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    candidate = tmp_path / "candidate.json"
    existing.write_text(json.dumps([_row(0), _row(3 * 86400)]), encoding="utf-8")
    candidate.write_text(json.dumps([_row(86400), _row(2 * 86400)]), encoding="utf-8")

    report = validate_candidate_coverage(
        candidate_path=candidate,
        existing_path=existing,
        product_id="BTC-USDC",
        timeframe="1D",
        gap_start=86400,
        gap_end_exclusive=3 * 86400,
    )

    assert report["validator_pass"] is True
    assert report["missing_expected_count"] == 0
    assert report["unexpected_count"] == 0
    assert report["existing_overlap_count"] == 0
    assert report["state_write_performed"] is False


def test_candidate_validator_blocks_extra_range(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    candidate = tmp_path / "candidate.json"
    existing.write_text(json.dumps([_row(0), _row(3 * 86400)]), encoding="utf-8")
    candidate.write_text(json.dumps([_row(86400), _row(2 * 86400), _row(4 * 86400)]), encoding="utf-8")

    report = validate_candidate_coverage(
        candidate_path=candidate,
        existing_path=existing,
        product_id="BTC-USDC",
        timeframe="1D",
        gap_start=86400,
        gap_end_exclusive=3 * 86400,
    )

    assert report["validator_pass"] is False
    assert "candidate_contains_unexpected_ranges" in report["blockers"]


def test_candidate_validator_blocks_overlap_existing(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    candidate = tmp_path / "candidate.json"
    existing.write_text(json.dumps([_row(0), _row(86400), _row(3 * 86400)]), encoding="utf-8")
    candidate.write_text(json.dumps([_row(86400), _row(2 * 86400)]), encoding="utf-8")

    report = validate_candidate_coverage(
        candidate_path=candidate,
        existing_path=existing,
        product_id="BTC-USDC",
        timeframe="1D",
        gap_start=86400,
        gap_end_exclusive=3 * 86400,
    )

    assert report["validator_pass"] is False
    assert "candidate_overlaps_existing_cache" in report["blockers"]


def test_filter_candidate_to_gap_removes_tail_fetch_extras(tmp_path) -> None:
    raw = tmp_path / "raw.json"
    filtered = tmp_path / "filtered.json"
    raw.write_text(json.dumps([_row(0), _row(86400), _row(2 * 86400), _row(3 * 86400)]), encoding="utf-8")

    result = filter_candidate_to_gap(
        raw_candidate_path=raw,
        filtered_candidate_path=filtered,
        gap_start=86400,
        gap_end_exclusive=3 * 86400,
        product_id="BTC-USDC",
        timeframe="1D",
    )

    rows = json.loads(filtered.read_text(encoding="utf-8"))
    assert result["filtered_count"] == 2
    assert [row["start"] for row in rows] == [86400, 2 * 86400]
    assert result["state_write_performed"] is False
