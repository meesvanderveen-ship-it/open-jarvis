from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS, normalize_timeframe
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


def _flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "state_write_performed": False,
        "live_order_action_performed": False,
        "coinbase_account_or_order_call_performed": False,
        "binance_account_or_order_call_performed": False,
        "binance_trading_endpoint_call_performed": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "learning_to_execution_enabled": False,
    }


def _rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _starts(rows: Iterable[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    for row in rows:
        try:
            out.append(int(row["start"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _issue(
    code: str,
    *,
    starts: List[int],
    severity: str,
    repairable_by_refetch: bool,
    requires_known_gap_policy: bool,
    blocks_merge: bool,
    blocks_normal_backtest: bool = True,
    allows_exploratory_only: bool = False,
) -> Dict[str, Any]:
    return {
        "code": code,
        "start_count": len(starts),
        "starts_sample": starts[:20],
        "severity": severity,
        "repairable_by_refetch": repairable_by_refetch,
        "requires_known_gap_policy": requires_known_gap_policy,
        "blocks_merge": blocks_merge,
        "blocks_normal_backtest": blocks_normal_backtest,
        "allows_exploratory_only": allows_exploratory_only,
    }


def validate_historical_gap(
    *,
    candidate_path: str | Path,
    existing_path: str | Path,
    product_id: str,
    timeframe: str,
    expected_start: int,
    expected_end_exclusive: int,
) -> Dict[str, Any]:
    timeframe_n = normalize_timeframe(timeframe)
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    expected: Set[int] = set(range(int(expected_start), int(expected_end_exclusive), step))
    candidate_rows = _rows(candidate_path)
    existing_rows = _rows(existing_path)
    candidate_seq = _starts(candidate_rows)
    candidate = set(candidate_seq)
    existing = set(_starts(existing_rows))
    missing = sorted(expected - candidate)
    unexpected = sorted(candidate - expected)
    overlap = sorted(candidate & existing)
    duplicate_count = len(candidate_seq) - len(candidate)
    bad_identity = [
        int(row.get("start"))
        for row in candidate_rows
        if str(row.get("product_id") or row.get("mapped_coinbase_product") or "").upper() != product_id.upper()
        or str(row.get("timeframe") or "").upper() != timeframe_n
    ]
    issues: List[Dict[str, Any]] = []
    if not candidate_rows:
        issues.append(_issue("partial_candidate_empty", starts=[], severity="blocker", repairable_by_refetch=True, requires_known_gap_policy=False, blocks_merge=True))
    if missing:
        issues.append(_issue("missing_starts", starts=missing, severity="blocker", repairable_by_refetch=True, requires_known_gap_policy=True, blocks_merge=True, allows_exploratory_only=True))
    if duplicate_count:
        issues.append(_issue("duplicate_starts", starts=[], severity="blocker", repairable_by_refetch=False, requires_known_gap_policy=False, blocks_merge=True))
    if unexpected:
        off_by_one = unexpected == [int(expected_start) - step] or unexpected == [int(expected_end_exclusive)]
        issues.append(_issue("off_by_one_boundary_issue" if off_by_one else "unexpected_starts", starts=unexpected, severity="blocker", repairable_by_refetch=not off_by_one, requires_known_gap_policy=False, blocks_merge=True))
    if overlap:
        issues.append(_issue("overlaps_existing_cache", starts=overlap, severity="blocker", repairable_by_refetch=False, requires_known_gap_policy=False, blocks_merge=True))
    if bad_identity:
        issues.append(_issue("source_or_interval_mismatch", starts=bad_identity[:20], severity="blocker", repairable_by_refetch=False, requires_known_gap_policy=False, blocks_merge=True))
    blocks_merge = any(issue["blocks_merge"] for issue in issues)
    data_hole_candidate = bool(missing) and not bad_identity
    return {
        "generated_at": now_iso(),
        "phase": "D6_historical_gap_validator_v1",
        "report_name": "historical_gap_validator_v1",
        "status": "historical_gap_validation_pass" if not blocks_merge else "historical_gap_validation_blocked",
        "candidate_path": str(assert_research_path(candidate_path)),
        "existing_path": str(assert_research_path(existing_path)),
        "product_id": product_id.upper(),
        "timeframe": timeframe_n,
        "expected_start": int(expected_start),
        "expected_end_exclusive": int(expected_end_exclusive),
        "expected_count": len(expected),
        "candidate_count": len(candidate),
        "missing_count": len(missing),
        "duplicate_count": duplicate_count,
        "overlap_count": len(overlap),
        "unexpected_count": len(unexpected),
        "interval_mismatch_count": len(bad_identity),
        "exchange_data_hole_candidate": data_hole_candidate,
        "blocks_merge": blocks_merge,
        "blocks_normal_backtest": blocks_merge,
        "allows_exploratory_only": data_hole_candidate,
        "issues": issues,
        **_flags(),
    }


__all__ = ["validate_historical_gap"]
