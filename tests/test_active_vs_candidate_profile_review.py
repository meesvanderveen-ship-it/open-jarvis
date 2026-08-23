from __future__ import annotations

import json
from pathlib import Path

from tools.build_active_vs_candidate_profile_review import build_review


def test_active_vs_candidate_review_is_read_only_and_flags_static_candidate(tmp_path: Path):
    state = tmp_path / "state"
    reports = tmp_path / "reports/backtests"
    research = tmp_path / "reports/research"
    state.mkdir(parents=True)
    reports.mkdir(parents=True)
    research.mkdir(parents=True)
    (state / "approved_parameter_profile.json").write_text(json.dumps({
        "profile_name": "active",
        "profile_version": 1,
        "parameters": {
            "DEFAULT_QUOTE_SIZE_USDC": "20.00",
            "MAX_NOTIONAL_USD": "20.00",
            "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
            "PHASE_C_MAX_ORDER_QUOTE": "20.00",
            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
            "MAX_SPREAD_PCT": "0.0060",
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
        },
    }), encoding="utf-8")
    (reports / "approved-profile-candidate-from-backtest.json").write_text(json.dumps({
        "hash_to_approve": "abc",
        "safe_to_live_activate_now": False,
        "requires_operator_review": True,
        "requires_exact_hash_ack": True,
        "candidate_is_static_research_prior": True,
        "candidate_not_metric_optimized": True,
        "supports_20_100_sizing": True,
        "metric_dependency": {
            "label_counts_used_for_parameters": False,
            "per_timeframe_results_used_for_parameters": False,
            "sample_size_used_for_confidence": True,
        },
        "approved_profile_json": {
            "profile_name": "research_prior_backtest_available_candidate",
            "profile_version": 1,
            "parameters": {
                "DEFAULT_QUOTE_SIZE_USDC": "20.00",
                "MAX_NOTIONAL_USD": "100.00",
                "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
                "PHASE_C_MAX_ORDER_QUOTE": "100.00",
                "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
                "MAX_SPREAD_PCT": "0.0060",
                "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0100",
                "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "2.5",
                "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.50",
                "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
            },
        },
    }), encoding="utf-8")
    (reports / "btc-eth-parameter-backtest-latest.json").write_text(json.dumps({
        "candidate": {"sample_size": 45662, "confidence": "medium", "overfit_risk": "medium"},
        "label_counts": {"good_entry_candidate": 581, "bad_entry_candidate": 2315, "missed_opportunity": 3471},
    }), encoding="utf-8")
    (research / "research-prior-parameter-profile-latest.json").write_text("{}", encoding="utf-8")

    report = build_review(
        active_path=state / "approved_parameter_profile.json",
        candidate_path=reports / "approved-profile-candidate-from-backtest.json",
        backtest_path=reports / "btc-eth-parameter-backtest-latest.json",
        research_path=research / "research-prior-parameter-profile-latest.json",
        generated_at="2026-06-14T00:00:00Z",
    )
    assert report["read_only"] is True
    assert report["coinbase_action_attempted"] is False
    assert report["candidate_static_or_adaptive"]["candidate_is_static_research_prior"] is True
    assert report["could_be_too_aggressive"] is True
    assert report["supports_20_100_sizing"] is True
    assert "activate_only" in report["recommendation"]

