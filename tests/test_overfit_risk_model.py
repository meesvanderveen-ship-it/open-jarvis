from __future__ import annotations

from bot.overfit_risk_model import (
    KNOWN_REGIMES,
    compute_overfit_risk,
    coverage_summary,
    direction_stability_score,
    normalize_label,
    regime_coverage,
    ticker_coverage,
    time_split_halves,
)


def test_normalize_label_buckets_garbled_dict_strings_as_unknown():
    garbled = "{'regime_label':_'mixed',_'regime_confidence':_0.86}"
    assert normalize_label(garbled) == "unknown"
    assert normalize_label(None) == "unknown"
    assert normalize_label("") == "unknown"
    assert normalize_label("trend_up") == "trend_up"


def test_coverage_summary_counts_and_dominant_share():
    evidence = [{"ticker": "BTC-USDC"}, {"ticker": "BTC-USDC"}, {"ticker": "ETH-USDC"}]
    summary = coverage_summary(evidence, key="ticker")
    assert summary["counts"] == {"btc-usdc": 2, "eth-usdc": 1}
    assert summary["total"] == 3
    assert summary["dominant_label"] == "btc-usdc"
    assert summary["dominant_share"] == 2 / 3


def test_regime_coverage_pct_uses_known_regimes_denominator():
    evidence = [{"regime": "trend_up"}, {"regime": "range_chop"}, {"regime": None}]
    coverage = regime_coverage(evidence)
    assert coverage["distinct_known"] == 2
    assert coverage["coverage_pct"] == round(2 / len(KNOWN_REGIMES), 4)
    assert set(coverage["known_regimes_seen"]) == {"trend_up", "range_chop"}


def test_ticker_coverage_lists_tickers_seen():
    evidence = [{"ticker": "ADA-USDC"}, {"ticker": "SOL-USDC"}]
    coverage = ticker_coverage(evidence)
    assert coverage["distinct_known"] == 2
    assert set(coverage["tickers_seen"]) == {"ada-usdc", "sol-usdc"}


def test_time_split_halves_orders_chronologically():
    evidence = [
        {"created_at": "2026-06-20T00:00:00Z", "id": "old"},
        {"created_at": "2026-06-22T00:00:00Z", "id": "new"},
        {"created_at": "2026-06-21T00:00:00Z", "id": "mid"},
    ]
    first, second = time_split_halves(evidence)
    assert [item["id"] for item in first] == ["old"]
    assert [item["id"] for item in second] == ["mid", "new"]


def test_direction_stability_score_consistent_direction():
    score, reason = direction_stability_score("loosen", "loosen", evidence_first=5, evidence_second=5)
    assert score == 1.0
    assert "consistent" in reason


def test_direction_stability_score_flip_is_zero():
    score, reason = direction_stability_score("loosen", "tighten", evidence_first=5, evidence_second=5)
    assert score == 0.0
    assert "flipped" in reason


def test_direction_stability_score_empty_half_is_partial():
    score, _ = direction_stability_score("loosen", "loosen", evidence_first=5, evidence_second=0)
    assert score == 0.4


def test_direction_stability_score_unresolved_direction_is_partial():
    score, _ = direction_stability_score("mixed", "loosen", evidence_first=5, evidence_second=5)
    assert score == 0.5


def test_compute_overfit_risk_no_evidence_is_high():
    assessment = compute_overfit_risk([])
    assert assessment.risk == "high"
    assert assessment.score == 1.0
    assert assessment.reasons == ("no_evidence_at_all",)


def test_compute_overfit_risk_sparse_single_ticker_single_regime_is_high():
    evidence = [{"ticker": "BTC-USDC", "regime": "trend_up"} for _ in range(3)]
    assessment = compute_overfit_risk(evidence)
    assert assessment.risk == "high"
    assert any("only_3" in reason for reason in assessment.reasons)


def test_compute_overfit_risk_broad_multi_regime_multi_ticker_is_low():
    regimes = ["trend_up", "trend_down", "range_chop", "high_volatility"]
    tickers = ["BTC-USDC", "ETH-USDC", "SOL-USDC", "ADA-USDC"]
    evidence = [
        {"ticker": tickers[i % len(tickers)], "regime": regimes[i % len(regimes)]} for i in range(24)
    ]
    assessment = compute_overfit_risk(evidence, direction_stability=1.0)
    assert assessment.risk == "low"
    assert assessment.score < 0.25


def test_compute_overfit_risk_unstable_direction_adds_penalty():
    evidence = [{"ticker": f"T{i}-USDC", "regime": "trend_up"} for i in range(25)]
    stable = compute_overfit_risk(evidence, direction_stability=1.0)
    unstable = compute_overfit_risk(evidence, direction_stability=0.0)
    assert unstable.score > stable.score
