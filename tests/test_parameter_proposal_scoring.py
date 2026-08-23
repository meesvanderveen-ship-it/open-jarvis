from __future__ import annotations

import itertools

from bot.parameter_proposal_scoring import (
    TIERS,
    classify_tier,
    evaluate_proposal,
    proposal_score,
    why_no_proposal,
    why_not_apply_ready,
)


def test_proposal_score_perfect_inputs_with_no_penalty_is_one():
    score = proposal_score(
        confidence=1.0,
        regime_coverage_pct=1.0,
        ticker_coverage_score=1.0,
        direction_stability=1.0,
        effect_size_quality=1.0,
        live_relevance=1.0,
    )
    assert score == 1.0


def test_proposal_score_zero_confidence_is_zero():
    score = proposal_score(
        confidence=0.0,
        regime_coverage_pct=1.0,
        ticker_coverage_score=1.0,
        direction_stability=1.0,
        effect_size_quality=1.0,
        live_relevance=1.0,
    )
    assert score == 0.0


def test_proposal_score_geometric_mean_softer_than_plain_product():
    # confidence=1.0 isolates the geometric-mean group: with all five other
    # factors at 0.5, a literal product would give 0.5**5 ~= 0.03125. The
    # geometric mean should preserve 0.5 so one weak-but-nonzero dimension
    # doesn't crush an otherwise-balanced signal.
    score = proposal_score(
        confidence=1.0,
        regime_coverage_pct=0.5,
        ticker_coverage_score=0.5,
        direction_stability=0.5,
        effect_size_quality=0.5,
        live_relevance=0.5,
    )
    assert score == 0.5
    assert score > 0.5**5


def test_proposal_score_penalties_are_subtracted_and_clamped():
    score = proposal_score(
        confidence=0.9,
        regime_coverage_pct=0.9,
        ticker_coverage_score=0.9,
        direction_stability=0.9,
        effect_size_quality=0.9,
        live_relevance=0.9,
        overfit_penalty=5.0,
        drawdown_penalty=5.0,
    )
    assert score == 0.0


def test_classify_tier_observed_signal_floor_cases():
    assert classify_tier(
        evidence_count=0, pressure_direction="no_signal", regimes_seen_count=0, tickers_seen_count=0,
        direction_stability=0.0, overfit_risk="high", score=0.0,
    ) == "observed_signal"
    assert classify_tier(
        evidence_count=3, pressure_direction="loosen", regimes_seen_count=1, tickers_seen_count=1,
        direction_stability=0.5, overfit_risk="high", score=0.1,
    ) == "observed_signal"
    assert classify_tier(
        evidence_count=20, pressure_direction="mixed", regimes_seen_count=4, tickers_seen_count=4,
        direction_stability=1.0, overfit_risk="low", score=0.9,
    ) == "observed_signal"


def test_classify_tier_shadow_candidate_below_backtest_floor():
    tier = classify_tier(
        evidence_count=10, pressure_direction="loosen", regimes_seen_count=1, tickers_seen_count=1,
        direction_stability=1.0, overfit_risk="medium", score=0.3,
    )
    assert tier == "shadow_candidate"


def test_classify_tier_backtest_candidate_below_walk_forward_floor():
    tier = classify_tier(
        evidence_count=25, pressure_direction="tighten", regimes_seen_count=2, tickers_seen_count=1,
        direction_stability=0.5, overfit_risk="medium", score=0.4,
    )
    assert tier == "backtest_candidate"


def test_classify_tier_walk_forward_candidate_when_overfit_not_low():
    tier = classify_tier(
        evidence_count=25, pressure_direction="loosen", regimes_seen_count=2, tickers_seen_count=2,
        direction_stability=1.0, overfit_risk="medium", score=0.4,
    )
    assert tier == "walk_forward_candidate"


def test_classify_tier_operator_review_candidate_best_case():
    tier = classify_tier(
        evidence_count=25, pressure_direction="loosen", regimes_seen_count=3, tickers_seen_count=3,
        direction_stability=1.0, overfit_risk="low", score=0.8,
    )
    assert tier == "operator_review_candidate"


def test_classify_tier_never_returns_apply_ready_for_any_extreme_input():
    extreme_values = [0, 1, 5, 50, 1000]
    directions = ["loosen", "tighten", "mixed", "no_signal", "keep"]
    risks = ["low", "medium", "high"]
    for evidence_count, direction, risk in itertools.product(extreme_values, directions, risks):
        tier = classify_tier(
            evidence_count=evidence_count,
            pressure_direction=direction,
            regimes_seen_count=50,
            tickers_seen_count=50,
            direction_stability=1.0,
            overfit_risk=risk,
            score=1.0,
        )
        assert tier in TIERS
        assert tier != "apply_ready_candidate"


def test_why_no_proposal_zero_evidence():
    text = why_no_proposal(evidence_count=0, pressure_direction="no_signal", tier="observed_signal", regimes_seen_count=0)
    assert "no evidence" in text.lower()


def test_why_no_proposal_mixed_signal():
    text = why_no_proposal(evidence_count=10, pressure_direction="mixed", tier="observed_signal", regimes_seen_count=1)
    assert "mixed" in text.lower()


def test_why_no_proposal_shadow_candidate_explains_volume_or_regime_gap():
    text = why_no_proposal(evidence_count=10, pressure_direction="loosen", tier="shadow_candidate", regimes_seen_count=1)
    assert "backtest_candidate" in text


def test_why_not_apply_ready_always_populated_and_never_promises_apply():
    for tier in TIERS:
        text = why_not_apply_ready(tier)
        assert text
        assert "governor" in text or "approved_parameter_profile" in text


def test_evaluate_proposal_end_to_end_consistency():
    evaluation = evaluate_proposal(
        evidence_count=25,
        pressure_direction="loosen",
        regimes_seen_count=3,
        tickers_seen_count=3,
        direction_stability=1.0,
        overfit_risk="low",
        confidence=0.9,
        regime_coverage_pct=0.9,
        ticker_coverage_score=0.9,
        effect_size_quality=0.9,
        live_relevance=0.9,
    )
    assert evaluation.tier == "operator_review_candidate"
    assert 0.0 <= evaluation.score <= 1.0
    assert evaluation.why_not_apply_ready
    as_dict = evaluation.to_dict()
    assert as_dict["tier"] == evaluation.tier
    assert as_dict["proposal_score"] == evaluation.score
