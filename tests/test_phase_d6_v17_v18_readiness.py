from bot.phase_d6_v17_v18_readiness import (
    MISSING_4H_START,
    build_backlearning_scaffold_v3,
    build_btc_1h_staged_rate_limited_plan_v2,
    build_btc_4h_gap_policy_v2,
    build_rate_limit_policy_v2,
)


def test_4h_gap_policy_blocks_incomplete_candidate_until_quality_exception() -> None:
    diagnostic = {
        "status": "btc_4h_surgical_gap_diagnostic_blocked",
        "classification": "known_exchange_data_hole_or_unresolved_candidate_gap",
        "candidate_validation": {
            "candidate_count": 3425,
            "expected_count": 3426,
            "missing_expected_count": 1,
            "missing_expected_starts_sample": [MISSING_4H_START],
            "validator_pass": False,
        },
        "rate_limited_fetch_result": {"first_candle_start": 1761393600},
    }

    report = build_btc_4h_gap_policy_v2(diagnostic=diagnostic)

    assert report["status"] == "btc_4h_gap_policy_blocked_until_quality_exception"
    assert report["known_gap_policy"]["may_merge_incomplete_candidate"] is False
    assert "dataset_quality_does_not_yet_support_documented_gap_exception" in report["blockers"]
    assert report["state_write_performed"] is False


def test_1h_rate_limited_plan_is_formally_blocked_by_4h_policy() -> None:
    one_h_policy = {
        "subruns": [
            {
                "subrun_id": "BTCUSDC-1H-gap01",
                "start": "2023-09-25T17:00:00Z",
                "end_exclusive": "2024-02-18T13:00:00Z",
                "expected_candle_count": 3500,
                "chunks_requested": 10,
            }
        ]
    }
    gap_policy = {"blockers": ["btc_4h_exact_candidate_validation_not_passed"]}

    report = build_btc_1h_staged_rate_limited_plan_v2(one_h_policy=one_h_policy, gap_policy=gap_policy, candidate_root="/tmp/x")

    assert report["status"] == "btc_1h_staged_rate_limited_plan_blocked"
    assert report["fetch_executed"] is False
    assert report["rate_limited_fetch_plan"]["request_count"] == 1
    assert report["rate_limited_fetch_plan"]["policy"]["max_consecutive_errors"] == 2


def test_rate_limit_policy_v2_has_resume_and_zero_candle_guardrails() -> None:
    report = build_rate_limit_policy_v2()

    assert report["policy"]["stop_on_zero_candle_response"] is True
    assert "resume_from_next_resume_chunk_index_only_after_review" in report["execution_rules"]
    assert "no_account_or_order_endpoint" in report["execution_rules"]


def test_backlearning_v3_keeps_execution_gate_closed() -> None:
    report = build_backlearning_scaffold_v3(
        quality_summary={"quality_report_count": 54, "good_count": 1, "warning_count": 53, "invalid_count": 0},
        gap_policy={"blockers": ["x"]},
    )

    assert report["execution_gate"]["runtime_mutation_allowed"] is False
    assert report["metrics"]["ranking_allowed"] is False
    assert "known_gap_exception_policy_not_implemented" in report["blockers"]
