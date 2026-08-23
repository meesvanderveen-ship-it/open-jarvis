"""Multi-tier parameter proposal scoring for the adaptive learning layer.

This module turns evidence statistics (already computed elsewhere -- see
``bot/adaptive_learning_intelligence.py`` and ``bot/overfit_risk_model.py``)
into two things: a single ``proposal_score`` float, and a discrete maturity
``tier``. Nothing here applies, activates or mutates anything. The existing
``autonomous_parameter_governor`` ACK flow and ``approved_parameter_profile``
gate remain the only route by which a parameter value can ever change.

Tier ladder (weakest to strongest evidence):
    observed_signal          -- some evidence exists, not yet shaped into a
                                 directional candidate.
    shadow_candidate         -- a stable direction with a minimum evidence
                                 floor; safe to show as "the bot is starting
                                 to think this", nothing more.
    backtest_candidate       -- enough volume and regime spread that a
                                 historical-replay check would be meaningful.
    walk_forward_candidate   -- direction holds up across an out-of-time
                                 split and more than one ticker.
    operator_review_candidate-- everything above plus low overfit risk and a
                                 high enough composite score to be worth a
                                 human actually reading.
    apply_ready_candidate    -- deliberately unreachable from this module.
                                 Activation is a governance decision, not a
                                 statistic; this learning layer never decides
                                 a parameter is ready to apply itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

TIERS: Tuple[str, ...] = (
    "observed_signal",
    "shadow_candidate",
    "backtest_candidate",
    "walk_forward_candidate",
    "operator_review_candidate",
    "apply_ready_candidate",
)

REAL_DIRECTIONS = frozenset({"loosen", "tighten"})

SHADOW_MIN_EVIDENCE = 8
BACKTEST_MIN_EVIDENCE = 20
BACKTEST_MIN_REGIMES = 2
WALK_FORWARD_MIN_TICKERS = 2
WALK_FORWARD_MIN_DIRECTION_STABILITY = 1.0
OPERATOR_REVIEW_MIN_SCORE = 0.5

#: Floor used inside the geometric mean so one missing dimension (e.g. a
#: brand-new parameter with zero regime spread so far) cannot collapse the
#: score to a value indistinguishable from "no evidence at all". A literal
#: product of several sub-1 factors decays far faster than evidence quality
#: actually should; the geometric mean plus this floor keeps the score
#: monotonic and interpretable while still requiring every dimension to be
#: decent for a high score.
_MIN_FACTOR_FLOOR = 1e-6


def proposal_score(
    *,
    confidence: float,
    regime_coverage_pct: float,
    ticker_coverage_score: float,
    direction_stability: float,
    effect_size_quality: float,
    live_relevance: float,
    overfit_penalty: float = 0.0,
    drawdown_penalty: float = 0.0,
) -> float:
    """Composite proposal quality score in [0, 1].

    ``proposal_score = confidence * geometric_mean(regime_coverage,
    ticker_coverage, direction_stability, effect_size_quality,
    live_relevance) - overfit_penalty - drawdown_penalty``

    ``confidence`` is a true multiplicative gate -- zero confidence means
    zero score, full stop. The other five evidence-quality dimensions are
    combined with a geometric mean (instead of a plain product) so that one
    weak-but-nonzero dimension does not crush an otherwise-decent signal to
    near zero; it still pulls the score down more than an arithmetic mean
    would, which is the intended "every dimension must be at least
    adequate" behaviour.
    """
    other_factors = (
        regime_coverage_pct,
        ticker_coverage_score,
        direction_stability,
        effect_size_quality,
        live_relevance,
    )
    clamped_others = [max(0.0, min(1.0, float(f))) for f in other_factors]
    product = 1.0
    for value in clamped_others:
        product *= max(value, _MIN_FACTOR_FLOOR)
    geometric_mean_others = product ** (1.0 / len(clamped_others))
    confidence_clamped = max(0.0, min(1.0, float(confidence)))
    score = confidence_clamped * geometric_mean_others - max(0.0, overfit_penalty) - max(0.0, drawdown_penalty)
    return round(max(0.0, min(1.0, score)), 4)


def classify_tier(
    *,
    evidence_count: int,
    pressure_direction: str,
    regimes_seen_count: int,
    tickers_seen_count: int,
    direction_stability: float,
    overfit_risk: str,
    score: float,
) -> str:
    """Map evidence statistics to a tier. Never returns apply_ready_candidate."""
    if evidence_count <= 0 or pressure_direction not in REAL_DIRECTIONS:
        return "observed_signal"
    if evidence_count < SHADOW_MIN_EVIDENCE:
        return "observed_signal"
    if evidence_count < BACKTEST_MIN_EVIDENCE or regimes_seen_count < BACKTEST_MIN_REGIMES:
        return "shadow_candidate"
    if direction_stability < WALK_FORWARD_MIN_DIRECTION_STABILITY or tickers_seen_count < WALK_FORWARD_MIN_TICKERS:
        return "backtest_candidate"
    if overfit_risk != "low" or score < OPERATOR_REVIEW_MIN_SCORE:
        return "walk_forward_candidate"
    return "operator_review_candidate"


def why_no_proposal(
    *,
    evidence_count: int,
    pressure_direction: str,
    tier: str,
    regimes_seen_count: int,
) -> str:
    """Human-readable, data-driven explanation -- an observation, not a blocker."""
    if evidence_count == 0:
        return (
            "No evidence yet: no decision/execution outcome in the lookback window "
            "carries a usable value for this parameter's evidence field."
        )
    if pressure_direction == "mixed":
        return (
            f"{evidence_count} evidence record(s) point in both directions across "
            "regimes/time -- treated as a mixed signal, not a proposal."
        )
    if pressure_direction == "no_signal":
        return (
            f"{evidence_count} evidence record(s) exist but none fall close enough to the "
            "current threshold to indicate pressure either way."
        )
    if tier == "observed_signal":
        return (
            f"Only {evidence_count} usable evidence record(s) seen so far -- below the "
            f"shadow_candidate floor of {SHADOW_MIN_EVIDENCE}."
        )
    if tier == "shadow_candidate":
        return (
            f"Direction is consistent across {evidence_count} record(s) but evidence volume "
            f"({evidence_count}) or regime spread ({regimes_seen_count} regime(s)) is still "
            f"below the backtest_candidate floor ({BACKTEST_MIN_EVIDENCE} records / "
            f"{BACKTEST_MIN_REGIMES} regimes)."
        )
    return ""


def why_not_apply_ready(tier: str) -> str:
    """Always populated: this layer never emits apply_ready_candidate."""
    if tier == "operator_review_candidate":
        return (
            "This learning layer stops at operator_review_candidate by design. Activation "
            "still requires the existing autonomous_parameter_governor ACK flow and "
            "approved_parameter_profile gate -- a statistic is never sufficient on its own."
        )
    return (
        "apply_ready_candidate is intentionally unreachable from this module; only the "
        "existing governed activation path (autonomous_parameter_governor + "
        "approved_parameter_profile) can ever mark a parameter ready to apply."
    )


@dataclass(frozen=True)
class ProposalEvaluation:
    tier: str
    score: float
    why_no_proposal: str
    why_not_apply_ready: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "proposal_score": self.score,
            "why_no_proposal": self.why_no_proposal,
            "why_not_apply_ready": self.why_not_apply_ready,
        }


def evaluate_proposal(
    *,
    evidence_count: int,
    pressure_direction: str,
    regimes_seen_count: int,
    tickers_seen_count: int,
    direction_stability: float,
    overfit_risk: str,
    confidence: float,
    regime_coverage_pct: float,
    ticker_coverage_score: float,
    effect_size_quality: float,
    live_relevance: float,
    overfit_penalty: float = 0.0,
    drawdown_penalty: float = 0.0,
) -> ProposalEvaluation:
    """One-call convenience wrapper around scoring + tiering + explanations."""
    score = proposal_score(
        confidence=confidence,
        regime_coverage_pct=regime_coverage_pct,
        ticker_coverage_score=ticker_coverage_score,
        direction_stability=direction_stability,
        effect_size_quality=effect_size_quality,
        live_relevance=live_relevance,
        overfit_penalty=overfit_penalty,
        drawdown_penalty=drawdown_penalty,
    )
    tier = classify_tier(
        evidence_count=evidence_count,
        pressure_direction=pressure_direction,
        regimes_seen_count=regimes_seen_count,
        tickers_seen_count=tickers_seen_count,
        direction_stability=direction_stability,
        overfit_risk=overfit_risk,
        score=score,
    )
    return ProposalEvaluation(
        tier=tier,
        score=score,
        why_no_proposal=why_no_proposal(
            evidence_count=evidence_count,
            pressure_direction=pressure_direction,
            tier=tier,
            regimes_seen_count=regimes_seen_count,
        ),
        why_not_apply_ready=why_not_apply_ready(tier),
    )


__all__ = [
    "TIERS",
    "REAL_DIRECTIONS",
    "SHADOW_MIN_EVIDENCE",
    "BACKTEST_MIN_EVIDENCE",
    "BACKTEST_MIN_REGIMES",
    "WALK_FORWARD_MIN_TICKERS",
    "WALK_FORWARD_MIN_DIRECTION_STABILITY",
    "OPERATOR_REVIEW_MIN_SCORE",
    "ProposalEvaluation",
    "proposal_score",
    "classify_tier",
    "why_no_proposal",
    "why_not_apply_ready",
    "evaluate_proposal",
]
