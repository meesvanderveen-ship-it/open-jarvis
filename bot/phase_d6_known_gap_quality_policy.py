from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from bot.phase_d6_candidate_coverage_validator import validate_candidate_coverage
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_known_gap_quality_policy_v1"
BTC_4H_CANDLES = "research_data/coinbase/candles/product=BTC-USDC/timeframe=4H/study_window=3y.json"
BTC_4H_COMBINED_CANDIDATE = "/tmp/d6_btc_4h_surgical_gap_20260601_v16/product=BTC-USDC/timeframe=4H/BTCUSDC-4H-gap01-combined.json"
BTC_4H_GAP_START = 1725912000
BTC_4H_GAP_END_EXCLUSIVE = 1775246400
BTC_4H_KNOWN_HOLE_START = 1761408000


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


def _iso_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _starts(rows: Iterable[Dict[str, Any]]) -> Set[int]:
    out: Set[int] = set()
    for row in rows:
        try:
            out.add(int(row.get("start")))
        except (TypeError, ValueError):
            continue
    return out


def build_known_gap_quality_policy_v1() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "known_gap_quality_policy_v1",
        "status": "known_gap_quality_policy_v1_ready",
        "gap_classes": {
            "unresolved_gap": {
                "exploratory_allowed": False,
                "normal_backtest_allowed": False,
                "merge_allowed": False,
            },
            "documented_exchange_data_hole_candidate": {
                "exploratory_allowed": False,
                "normal_backtest_allowed": False,
                "merge_allowed": False,
                "requires_candidate_context": True,
            },
            "acceptable_known_gap_for_exploratory_research": {
                "exploratory_allowed": True,
                "normal_backtest_allowed": False,
                "merge_allowed": False,
                "requires_explicit_missing_start_list": True,
                "requires_single_product_timeframe_scope": True,
            },
            "unacceptable_for_normal_backtest_evidence": {
                "exploratory_allowed": False,
                "normal_backtest_allowed": False,
                "merge_allowed": False,
            },
        },
        "invariants": [
            "no_synthetic_ohlcv",
            "no_fake_candle",
            "no_raw_cache_mutation",
            "no_incomplete_candidate_merge",
            "known_gap_remains_visible",
            "normal_backtests_remain_blocked",
        ],
        "open_source_pattern_map": {
            "freqtrade": ["separate_data_refresh_from_backtest", "protect_backtest_from_missing_data"],
            "ccxt": ["expect_exchange_ohlcv_holes", "explicit_pagination_and_rate_limits"],
            "vectorbt": ["local_metric_plumbing_only", "research_grid_is_not_runtime_decision"],
            "hummingbot": ["separate_data_lifecycle_from_execution_lifecycle"],
        },
        **safety_flags(),
        "state_write_performed": False,
    }


def build_btc_4h_known_gap_preview_v1(
    *,
    candidate_path: str | Path = BTC_4H_COMBINED_CANDIDATE,
    existing_path: str | Path = BTC_4H_CANDLES,
    known_gap_starts: Iterable[int] = (BTC_4H_KNOWN_HOLE_START,),
    as_of: str = "2026-06-01T00:00:00Z",
) -> Dict[str, Any]:
    known = sorted({int(item) for item in known_gap_starts})
    validation = validate_candidate_coverage(
        candidate_path=candidate_path,
        existing_path=existing_path,
        product_id="BTC-USDC",
        timeframe="4H",
        gap_start=BTC_4H_GAP_START,
        gap_end_exclusive=BTC_4H_GAP_END_EXCLUSIVE,
    )
    missing = sorted(int(item) for item in validation.get("missing_expected_starts_sample") or [])
    candidate_rows = _load_rows(candidate_path)
    candidate_starts = _starts(candidate_rows)
    known_set = set(known)
    unexplained_missing = sorted(set(missing) - known_set)
    known_present_in_candidate = sorted(candidate_starts & known_set)
    quality = build_phase_d6_dataset_quality_report(candles_path=existing_path, as_of=as_of)
    acceptable_preview = (
        bool(candidate_rows)
        and validation.get("candidate_count") == validation.get("expected_count") - len(known_set)
        and set(missing) == known_set
        and not validation.get("unexpected_count")
        and not validation.get("duplicate_count")
        and not validation.get("bad_identity_count")
        and not validation.get("existing_overlap_count")
    )
    status = "btc_4h_known_gap_preview_ready" if acceptable_preview else "btc_4h_known_gap_preview_blocked"
    gap_class = "acceptable_known_gap_for_exploratory_research" if acceptable_preview else "documented_exchange_data_hole_candidate"
    blockers: List[str] = []
    if not acceptable_preview:
        blockers.append("candidate_not_acceptable_after_known_gap_policy")
    if unexplained_missing:
        blockers.append("unexplained_missing_expected_starts_remain")
    if known_present_in_candidate:
        blockers.append("known_gap_start_unexpectedly_present_in_candidate")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_4h_known_gap_preview_v1",
        "status": status,
        "product_id": "BTC-USDC",
        "timeframe": "4H",
        "known_gap_starts": known,
        "known_gap_start_iso": [_iso_from_ts(item) for item in known],
        "gap_class": gap_class,
        "candidate_path": str(assert_research_path(candidate_path)),
        "existing_path": str(assert_research_path(existing_path)),
        "candidate_validation": validation,
        "raw_cache_quality": {
            "quality_class": quality.get("quality_class"),
            "gap_count": quality.get("gap_count"),
            "missing_candle_estimate": quality.get("missing_candle_estimate"),
            "warnings": quality.get("warnings"),
        },
        "preview_semantics": {
            "raw_cache_mutated": False,
            "candidate_merged": False,
            "synthetic_ohlcv_created": False,
            "normal_backtest_allowed": False,
            "exploratory_only_allowed_for_this_candidate_scope": acceptable_preview,
            "known_gap_remains_visible": True,
        },
        "unexplained_missing_expected_starts": unexplained_missing,
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "BTC_4H_CANDLES",
    "BTC_4H_COMBINED_CANDIDATE",
    "BTC_4H_GAP_END_EXCLUSIVE",
    "BTC_4H_GAP_START",
    "BTC_4H_KNOWN_HOLE_START",
    "PHASE",
    "build_btc_4h_known_gap_preview_v1",
    "build_known_gap_quality_policy_v1",
    "safety_flags",
]
