import json

from bot.phase_d6_bounded_coverage_expansion import (
    build_coverage_expansion_result,
    discover_candidate_candle_pairs,
    merge_candidate_candles,
)


def test_merge_candidate_candles_only_updates_when_candidate_expands(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    candidate = tmp_path / "candidate.json"
    existing.write_text(json.dumps([{"start": 1, "close": "1"}]), encoding="utf-8")
    candidate.write_text(json.dumps([{"start": 1, "close": "1"}, {"start": 2, "close": "2"}]), encoding="utf-8")

    result = merge_candidate_candles(existing_path=existing, candidate_path=candidate)

    assert result["before_count"] == 1
    assert result["candidate_count"] == 2
    assert result["after_count"] == 2
    assert result["updated"] is True
    assert json.loads(existing.read_text(encoding="utf-8"))[-1]["start"] == 2


def test_coverage_expansion_result_is_research_only() -> None:
    report = build_coverage_expansion_result(
        merge_results=[
            {
                "existing_path": "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json",
                "before_count": 700,
                "after_count": 1400,
                "updated": True,
            }
        ],
        max_chunks=4,
        public_call_count=8,
    )

    assert report["coinbase_public_market_data_call_count"] == 8
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_enabled"] is False


def test_discover_candidate_candle_pairs_for_multiple_products(tmp_path) -> None:
    root = tmp_path / "candidate"
    eth = root / "product=ETH-USDC" / "timeframe=1H" / "study_window=3y.json"
    sol = root / "product=SOL-USDC" / "timeframe=4H" / "study_window=3y.json"
    eth.parent.mkdir(parents=True)
    sol.parent.mkdir(parents=True)
    eth.write_text("[]", encoding="utf-8")
    sol.write_text("[]", encoding="utf-8")

    pairs = discover_candidate_candle_pairs(candidate_root=root)

    assert [pair["product"] for pair in pairs] == ["ETH-USDC", "SOL-USDC"]
    assert pairs[0]["existing_path"] == "research_data/coinbase/candles/product=ETH-USDC/timeframe=1H/study_window=3y.json"
    assert pairs[1]["existing_path"] == "research_data/coinbase/candles/product=SOL-USDC/timeframe=4H/study_window=3y.json"
