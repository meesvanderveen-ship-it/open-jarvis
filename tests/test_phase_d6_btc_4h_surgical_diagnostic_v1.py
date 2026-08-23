import json

from tools import build_phase_d6_backlearning_scaffold_v2 as runner


def test_btc_4h_surgical_diagnostic_dry_run_uses_previous_candidate(tmp_path, monkeypatch) -> None:
    previous = tmp_path / "previous.json"
    existing = tmp_path / "existing.json"
    previous.write_text(json.dumps([{"start": 1761393600, "product_id": "BTC-USDC", "timeframe": "4H"}]), encoding="utf-8")
    existing.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(runner, "PREVIOUS_4H_CANDIDATE", str(previous))
    monkeypatch.setattr(runner, "BTC_4H_CANDLES", str(existing))

    report = runner.build_btc_4h_surgical_diagnostic(fetch_result=None, merge=False)

    assert report["status"] == "btc_4h_surgical_gap_diagnostic_ready"
    assert report["previous_candidate_count"] == 1
    assert report["rate_limited_fetch_plan"]["request_count"] == 1
    assert report["merge_executed"] is False
    assert report["state_write_performed"] is False


def test_btc_1h_policy_defers_until_4h_resolved() -> None:
    staged = {
        "subruns": [
            {
                "timeframe": "1H",
                "subrun_id": "BTCUSDC-1H-gap01",
                "subrange_start_iso": "2023-09-25T17:00:00Z",
                "subrange_end_exclusive_iso": "2024-02-18T13:00:00Z",
                "expected_candle_count": 3500,
                "chunks_requested": 10,
            }
        ]
    }

    report = runner.build_btc_1h_staged_policy(staged_plan=staged, diagnostic={"merge_executed": False})

    assert report["v16_execution_decision"] == "defer_1h_until_4h_resolved"
    assert report["rate_limit_policy_per_subrun"]["partial_candidate_quarantine"] is True

