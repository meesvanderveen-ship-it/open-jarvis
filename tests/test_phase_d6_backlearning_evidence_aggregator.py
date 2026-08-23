from bot.phase_d6_non_live_readiness_continuation import build_backlearning_evidence_aggregator


def test_backlearning_evidence_aggregator_keeps_parameter_review_blocked() -> None:
    readiness_matrix = {
        "content": {
            "rows": [
                {
                    "ticker": "BTC-USDC",
                    "required_timeframes_missing": ["1H", "4H"],
                    "dataset_quality_present": False,
                    "baseline_backtest_possible": True,
                    "cost_scenario_support_present": True,
                    "fill_realism_evidence_present": True,
                }
            ]
        }
    }
    workflow = {"content": {"rows": [{"ticker": "BTC-USDC", "lifecycle_evidence": True}]}}
    report = build_backlearning_evidence_aggregator(
        dataset_plan={"content": {"rows": []}},
        readiness_matrix=readiness_matrix,
        backlearning_review={"content": {"status": "blocked"}},
        guardrails={"content": {"status": "blocked"}},
        workflow_equivalence=workflow,
    )

    assert report["parameter_review_blocked"] is True
    assert report["parameter_review_approved"] is False
    assert report["optimization_performed"] is False
    assert report["learning_to_execution_enabled"] is False
    assert report["rows"][0]["parameter_review_status"] == "blocked"
