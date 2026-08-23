from __future__ import annotations

from bot.phase_d6_multi_ticker_backlearning_readiness import (
    build_backlearning_parameter_candidate_scaffold,
    build_backlearning_trial_accounting_guardrails,
)


def _matrix():
    return {
        "rows": [
            {
                "ticker": "BTC-USDC",
                "required_timeframes_missing": ["1H", "4H"],
                "dataset_quality_present": False,
                "baseline_backtest_possible": True,
                "fill_realism_evidence_present": True,
            },
            {
                "ticker": "ETH-USDC",
                "required_timeframes_missing": ["1H", "4H", "1D"],
                "dataset_quality_present": False,
                "baseline_backtest_possible": False,
                "fill_realism_evidence_present": False,
            },
        ]
    }


def test_backlearning_candidate_scaffold_is_human_review_only_and_does_not_choose_winners():
    guardrails = build_backlearning_trial_accounting_guardrails(readiness_matrix=_matrix())
    report = build_backlearning_parameter_candidate_scaffold(readiness_matrix=_matrix(), guardrails=guardrails)

    rows = {row["ticker"]: row for row in report["rows"]}
    assert rows["BTC-USDC"]["human_ack_required_for_real_parameter_review"] is True
    assert rows["ETH-USDC"]["parameter_review_approved"] is False
    assert report["summary"]["all_parameter_reviews_blocked"] is True
    assert report["optimization_performed"] is False
    assert report["ranking_performed"] is False
    assert report["parameter_values_changed"] is False
    assert report["learning_to_execution_enabled"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
