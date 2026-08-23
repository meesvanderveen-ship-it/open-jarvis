from __future__ import annotations

from bot.phase_d6_multi_ticker_backlearning_readiness import build_backlearning_trial_accounting_guardrails


def test_trial_accounting_blocks_review_when_data_and_oos_are_missing():
    matrix = {
        "rows": [
            {
                "ticker": "BTC-USDC",
                "required_timeframes_missing": ["1H"],
                "dataset_quality_present": False,
                "baseline_backtest_possible": True,
                "fill_realism_evidence_present": True,
            }
        ]
    }
    report = build_backlearning_trial_accounting_guardrails(readiness_matrix=matrix)
    row = report["rows"][0]

    assert row["trial_count_recorded"] == 0
    assert row["oos_holdout_label_required"] is True
    assert row["parameter_review_blocked"] is True
    assert "incomplete_multi_timeframe_data" in row["block_reasons"]
    assert "missing_out_of_sample_windows" in row["block_reasons"]
    assert report["summary"]["optimization_performed"] is False
    assert report["summary"]["ranking_performed"] is False
    assert report["learning_to_execution_enabled"] is False
