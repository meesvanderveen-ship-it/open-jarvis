import json
from pathlib import Path

from bot.phase_d6_known_gap_policy_review import build_known_gap_policy_review


def _write(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_policy_review_allows_continuation_only_with_known_gap(tmp_path: Path) -> None:
    missing = [10, 20, 30, 40, 50]
    decision = _write(
        tmp_path / "decision.json",
        {
            "content": {
                "chunk_id": "BTCUSDC-1H-gap01:chunk52",
                "classification": "confirmed_coinbase_data_hole_candidate",
                "failed_candidate_validation": {
                    "issues": [{"code": "missing_starts", "starts_sample": missing}],
                    "overlap_count": 1,
                },
            }
        },
    )
    existing = _write(tmp_path / "existing.json", [])
    failed = _write(tmp_path / "failed.json", [{"start": 0}])
    adjusted = _write(tmp_path / "adjusted.json", {"content": {"status": "blocked", "candidate_validation": {"missing_expected_count": 5}}})

    report = build_known_gap_policy_review(decision_report_path=decision, existing_cache_path=existing, failed_candidate_path=failed, adjusted_result_path=adjusted)

    assert report["classification"] == "confirmed_primary_source_data_hole"
    assert report["missing_coinbase_starts"] == missing
    assert report["policy_decision"]["blocks_merge"] is True
    assert report["policy_decision"]["allows_exploratory_only"] is True
    assert report["policy_decision"]["allows_chunk53_continuation"] is True
    assert report["policy_decision"]["blocks_normal_backtest"] is True
