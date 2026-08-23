from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS, normalize_timeframe
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_candidate_coverage_validator_v1"


def safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "live_order_action_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
        "coinbase_account_or_order_call_performed": False,
    }


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _starts(rows: Iterable[Dict[str, Any]]) -> Set[int]:
    starts: Set[int] = set()
    for row in rows:
        try:
            starts.add(int(row.get("start")))
        except (TypeError, ValueError):
            continue
    return starts


def _expected_starts(*, gap_start: int, gap_end_exclusive: int, step_seconds: int) -> Set[int]:
    if gap_end_exclusive <= gap_start:
        return set()
    return set(range(int(gap_start), int(gap_end_exclusive), int(step_seconds)))


def filter_candidate_to_gap(
    *,
    raw_candidate_path: str | Path,
    filtered_candidate_path: str | Path,
    gap_start: int,
    gap_end_exclusive: int,
    product_id: str,
    timeframe: str,
) -> Dict[str, Any]:
    raw_path = assert_research_path(raw_candidate_path)
    filtered_path = assert_research_path(filtered_candidate_path)
    rows = _load_rows(raw_path)
    timeframe_n = normalize_timeframe(timeframe)
    filtered: List[Dict[str, Any]] = []
    outside_count = 0
    for row in rows:
        try:
            start = int(row.get("start"))
        except (TypeError, ValueError):
            continue
        if gap_start <= start < gap_end_exclusive:
            if str(row.get("product_id") or "").upper() == product_id.upper() and str(row.get("timeframe") or "").upper() == timeframe_n:
                filtered.append(dict(row))
        else:
            outside_count += 1
    filtered = [row for _, row in sorted({int(row["start"]): row for row in filtered}.items())]
    filtered_path.parent.mkdir(parents=True, exist_ok=True)
    filtered_path.write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "status": "candidate_gap_filter_written",
        "raw_candidate_path": str(raw_path),
        "filtered_candidate_path": str(filtered_path),
        "raw_count": len(rows),
        "filtered_count": len(filtered),
        "outside_gap_count": outside_count,
        "gap_start": int(gap_start),
        "gap_end_exclusive": int(gap_end_exclusive),
        "product_id": product_id.upper(),
        "timeframe": timeframe_n,
        **safety_flags(),
        "state_write_performed": False,
    }


def validate_candidate_coverage(
    *,
    candidate_path: str | Path,
    existing_path: str | Path,
    product_id: str,
    timeframe: str,
    gap_start: int,
    gap_end_exclusive: int,
) -> Dict[str, Any]:
    candidate_safe = assert_research_path(candidate_path)
    existing_safe = assert_research_path(existing_path)
    timeframe_n = normalize_timeframe(timeframe)
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    candidate_rows = _load_rows(candidate_safe)
    existing_rows = _load_rows(existing_safe)
    expected = _expected_starts(gap_start=int(gap_start), gap_end_exclusive=int(gap_end_exclusive), step_seconds=step)
    candidate_starts = _starts(candidate_rows)
    existing_starts = _starts(existing_rows)
    missing = sorted(expected - candidate_starts)
    unexpected = sorted(candidate_starts - expected)
    duplicate_count = len([row for row in candidate_rows if "start" in row]) - len(candidate_starts)
    bad_identity_count = sum(
        1
        for row in candidate_rows
        if str(row.get("product_id") or "").upper() != product_id.upper()
        or str(row.get("timeframe") or "").upper() != timeframe_n
    )
    existing_overlap = sorted(candidate_starts & existing_starts)
    blockers: List[str] = []
    if "state" in {part.lower() for part in candidate_safe.parts} or "state" in {part.lower() for part in existing_safe.parts}:
        blockers.append("state_path_refused")
    if not candidate_rows:
        blockers.append("candidate_empty")
    if missing:
        blockers.append("candidate_missing_expected_gap_starts")
    if unexpected:
        blockers.append("candidate_contains_unexpected_ranges")
    if duplicate_count:
        blockers.append("candidate_duplicate_starts")
    if bad_identity_count:
        blockers.append("candidate_product_or_timeframe_mismatch")
    if existing_overlap:
        blockers.append("candidate_overlaps_existing_cache")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "candidate_coverage_validator_v1",
        "status": "candidate_coverage_validation_pass" if not blockers else "candidate_coverage_validation_blocked",
        "candidate_path": str(candidate_safe),
        "existing_path": str(existing_safe),
        "product_id": product_id.upper(),
        "timeframe": timeframe_n,
        "gap_start": int(gap_start),
        "gap_end_exclusive": int(gap_end_exclusive),
        "timeframe_seconds": step,
        "expected_count": len(expected),
        "candidate_count": len(candidate_starts),
        "existing_count": len(existing_starts),
        "missing_expected_count": len(missing),
        "unexpected_count": len(unexpected),
        "duplicate_count": duplicate_count,
        "bad_identity_count": bad_identity_count,
        "existing_overlap_count": len(existing_overlap),
        "missing_expected_starts_sample": missing[:10],
        "unexpected_starts_sample": unexpected[:10],
        "existing_overlap_sample": existing_overlap[:10],
        "validator_pass": not blockers,
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "PHASE",
    "filter_candidate_to_gap",
    "safety_flags",
    "validate_candidate_coverage",
]
