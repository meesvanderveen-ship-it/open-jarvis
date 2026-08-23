import json

from bot.phase_d6_known_gap_quality_policy import (
    BTC_4H_GAP_END_EXCLUSIVE,
    BTC_4H_GAP_START,
    BTC_4H_KNOWN_HOLE_START,
    build_btc_4h_known_gap_preview_v1,
    build_known_gap_quality_policy_v1,
)


def _row(start: int) -> dict:
    return {
        "product_id": "BTC-USDC",
        "timeframe": "4H",
        "start": start,
        "open": "1",
        "high": "2",
        "low": "1",
        "close": "2",
        "volume": "1",
    }


def test_known_gap_policy_preserves_no_synthetic_invariant() -> None:
    report = build_known_gap_quality_policy_v1()

    assert report["status"] == "known_gap_quality_policy_v1_ready"
    assert "no_synthetic_ohlcv" in report["invariants"]
    assert report["gap_classes"]["acceptable_known_gap_for_exploratory_research"]["normal_backtest_allowed"] is False


def test_btc_4h_known_gap_preview_accepts_candidate_scope_without_mutating_raw(tmp_path) -> None:
    candidate = tmp_path / "candidate.json"
    existing = tmp_path / "existing.json"
    starts = [start for start in range(BTC_4H_GAP_START, BTC_4H_GAP_END_EXCLUSIVE, 14400) if start != BTC_4H_KNOWN_HOLE_START]
    candidate.write_text(json.dumps([_row(start) for start in starts]), encoding="utf-8")
    existing.write_text(json.dumps([_row(BTC_4H_GAP_START - 14400), _row(BTC_4H_GAP_END_EXCLUSIVE)]), encoding="utf-8")

    report = build_btc_4h_known_gap_preview_v1(candidate_path=candidate, existing_path=existing)

    assert report["status"] == "btc_4h_known_gap_preview_ready"
    assert report["gap_class"] == "acceptable_known_gap_for_exploratory_research"
    assert report["preview_semantics"]["synthetic_ohlcv_created"] is False
    assert report["preview_semantics"]["raw_cache_mutated"] is False
    assert report["preview_semantics"]["normal_backtest_allowed"] is False
