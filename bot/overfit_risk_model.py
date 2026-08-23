"""Overfitting protection for the adaptive learning layer.

Pure, deterministic scoring functions used to judge whether a piece of
parameter evidence is broad and stable enough to trust, or narrow enough
that a proposal built from it would likely be overfit to one ticker, one
regime, or one short time window.

Nothing here blocks anything at runtime. It only produces a risk label and
human-readable reasons that the proposal scoring and dashboard layers attach
to each candidate -- the existing approved-profile/governor ACK gates remain
the only route by which a parameter value can ever change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from bot.growbot_river_learning_contract import CANONICAL_REGIMES

KNOWN_REGIMES: Tuple[str, ...] = tuple(r for r in CANONICAL_REGIMES if r != "unknown")

MIN_EVIDENCE_FOR_MEDIUM = 8
MIN_EVIDENCE_FOR_LOW_RISK = 20
DOMINANT_SHARE_HIGH_RISK = 0.85
DOMINANT_SHARE_MEDIUM_RISK = 0.6
MIN_REGIMES_FOR_LOW_RISK = 2
_UNUSABLE_LABEL_VALUES = {"none", "null", "n/a", "na", "unknown", ""}


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (with or without a trailing Z), or None."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_parse_ts = parse_timestamp


def normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text in _UNUSABLE_LABEL_VALUES:
        return "unknown"
    # Defensive: some historical decision_outcomes records stored a
    # stringified dict instead of a short regime label upstream (a pre-
    # existing data-quality issue, not something this module fixes). Treat
    # anything implausibly long or with structural punctuation as unusable
    # rather than let it pollute regime/ticker coverage counts.
    if len(text) > 40 or any(ch in text for ch in "{}[]:"):
        return "unknown"
    return text


def coverage_summary(evidence: Sequence[Mapping[str, Any]], *, key: str) -> Dict[str, Any]:
    """Count how many evidence items fall into each value of `key`.

    `key` is typically "regime" or "ticker". Unusable/garbled values are
    bucketed under "unknown" rather than discarded, so the unknown share is
    itself visible as a coverage gap.
    """
    counts: Dict[str, int] = {}
    for item in evidence:
        label = normalize_label(item.get(key))
        counts[label] = counts.get(label, 0) + 1
    total = sum(counts.values())
    known_counts = {k: v for k, v in counts.items() if k != "unknown"}
    distinct_known = len(known_counts)
    dominant_label, dominant_count = max(counts.items(), key=lambda kv: kv[1]) if counts else (None, 0)
    return {
        "counts": counts,
        "total": total,
        "distinct_known": distinct_known,
        "dominant_label": dominant_label,
        "dominant_share": (dominant_count / total) if total else 0.0,
    }


def regime_coverage(evidence: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    summary = coverage_summary(evidence, key="regime")
    summary["coverage_pct"] = round(summary["distinct_known"] / len(KNOWN_REGIMES), 4) if KNOWN_REGIMES else 0.0
    summary["known_regimes_seen"] = sorted(k for k in summary["counts"] if k != "unknown")
    return summary


def ticker_coverage(evidence: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    summary = coverage_summary(evidence, key="ticker")
    summary["tickers_seen"] = sorted(k for k in summary["counts"] if k != "unknown")
    return summary


def time_split_halves(
    evidence: Sequence[Mapping[str, Any]], *, ts_key: str = "created_at"
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Split evidence chronologically into an earlier and later half.

    This is the train/test-over-time split used for direction-stability
    checks: a real signal should point the same way in both halves, not
    only in whichever half happens to contain more data.
    """
    dated = [(item, _parse_ts(item.get(ts_key))) for item in evidence]
    dated.sort(key=lambda pair: pair[1] or datetime.min.replace(tzinfo=timezone.utc))
    midpoint = len(dated) // 2
    first_half = [item for item, _ in dated[:midpoint]]
    second_half = [item for item, _ in dated[midpoint:]]
    return first_half, second_half


def direction_stability_score(
    direction_first_half: str,
    direction_second_half: str,
    *,
    evidence_first: int,
    evidence_second: int,
) -> Tuple[float, str]:
    """Compare the signal direction computed independently on each time half.

    Returns (score in [0, 1], reason). 1.0 only when both halves carry
    evidence and agree on a real (non-"keep"/"mixed"/"no_signal") direction.
    """
    real_directions = {"loosen", "tighten"}
    if evidence_first == 0 or evidence_second == 0:
        return 0.4, "one_time_half_has_no_evidence_yet"
    if direction_first_half not in real_directions or direction_second_half not in real_directions:
        return 0.5, "direction_not_resolved_in_one_or_both_halves"
    if direction_first_half == direction_second_half:
        return 1.0, "direction_consistent_across_earlier_and_later_evidence"
    return 0.0, "direction_flipped_between_earlier_and_later_evidence"


@dataclass(frozen=True)
class OverfitAssessment:
    risk: str
    score: float
    reasons: Tuple[str, ...]
    regime_coverage: Dict[str, Any]
    ticker_coverage: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk": self.risk,
            "score": self.score,
            "reasons": list(self.reasons),
            "regime_coverage_pct": self.regime_coverage.get("coverage_pct"),
            "known_regimes_seen": self.regime_coverage.get("known_regimes_seen"),
            "tickers_seen": self.ticker_coverage.get("tickers_seen"),
            "dominant_ticker_share": self.ticker_coverage.get("dominant_share"),
        }


def compute_overfit_risk(
    evidence: Sequence[Mapping[str, Any]],
    *,
    direction_stability: Optional[float] = None,
) -> OverfitAssessment:
    """Score how likely a proposal built from `evidence` is to be overfit.

    Combines evidence volume, regime coverage, ticker concentration and (if
    supplied) direction stability across a time split. Never raises and
    never blocks anything -- callers decide what tier/score this risk feeds
    into.
    """
    evidence_count = len(evidence)
    regimes = regime_coverage(evidence)
    tickers = ticker_coverage(evidence)

    if evidence_count == 0:
        return OverfitAssessment("high", 1.0, ("no_evidence_at_all",), regimes, tickers)

    reasons: List[str] = []
    score = 0.0

    if evidence_count < MIN_EVIDENCE_FOR_MEDIUM:
        score += 0.45
        reasons.append(f"only_{evidence_count}_evidence_record(s)_below_floor_of_{MIN_EVIDENCE_FOR_MEDIUM}")
    elif evidence_count < MIN_EVIDENCE_FOR_LOW_RISK:
        score += 0.2
        reasons.append(f"{evidence_count}_evidence_records_below_low_risk_floor_of_{MIN_EVIDENCE_FOR_LOW_RISK}")

    if regimes["distinct_known"] == 0:
        score += 0.3
        reasons.append("no_known_market_regime_tag_on_any_evidence_record")
    elif regimes["distinct_known"] < MIN_REGIMES_FOR_LOW_RISK:
        score += 0.15
        reasons.append("evidence_concentrated_in_a_single_market_regime")

    if tickers["dominant_share"] >= DOMINANT_SHARE_HIGH_RISK and tickers["total"] > 1:
        score += 0.25
        reasons.append(f"single_ticker_dominance_{tickers['dominant_label']}_{tickers['dominant_share']:.0%}")
    elif tickers["dominant_share"] >= DOMINANT_SHARE_MEDIUM_RISK and tickers["distinct_known"] > 1:
        score += 0.1
        reasons.append(f"ticker_concentration_{tickers['dominant_label']}_{tickers['dominant_share']:.0%}")
    elif tickers["distinct_known"] <= 1:
        score += 0.15
        reasons.append("only_one_ticker_has_contributed_evidence")

    if direction_stability is not None and direction_stability < 1.0:
        score += (1.0 - direction_stability) * 0.3
        if direction_stability == 0.0:
            reasons.append("direction_unstable_across_earlier_vs_later_evidence")

    score = round(min(score, 1.0), 4)
    if score >= 0.55:
        risk = "high"
    elif score >= 0.25:
        risk = "medium"
    else:
        risk = "low"
    if not reasons:
        reasons.append("evidence_volume_regime_and_ticker_coverage_all_adequate")
    return OverfitAssessment(risk, score, tuple(reasons), regimes, tickers)


__all__ = [
    "KNOWN_REGIMES",
    "OverfitAssessment",
    "parse_timestamp",
    "normalize_label",
    "coverage_summary",
    "regime_coverage",
    "ticker_coverage",
    "time_split_halves",
    "direction_stability_score",
    "compute_overfit_risk",
]
