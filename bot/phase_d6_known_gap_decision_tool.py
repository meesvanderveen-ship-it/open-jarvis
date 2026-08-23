from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_historical_gap_validator import validate_historical_gap
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


def _load_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    return dict(loaded.get("content") or loaded)


def build_known_gap_decision(
    *,
    chunk_id: str,
    expected_start: int,
    expected_end_exclusive: int,
    existing_path: str | Path,
    failed_candidate_path: str | Path,
    adjusted_result_path: str | Path | None = None,
    binance_reference_paths: Iterable[str | Path] | None = None,
) -> Dict[str, Any]:
    failed_validation = validate_historical_gap(
        candidate_path=failed_candidate_path,
        existing_path=existing_path,
        product_id="BTC-USDC",
        timeframe="1H",
        expected_start=expected_start,
        expected_end_exclusive=expected_end_exclusive,
    )
    adjusted = _load_content(adjusted_result_path) if adjusted_result_path else {}
    adjusted_validation = dict(adjusted.get("candidate_validation") or {})
    missing_after_adjusted = int(adjusted_validation.get("missing_expected_count") or adjusted_validation.get("missing_count") or 0)
    reference_paths = [str(assert_research_path(path)) for path in binance_reference_paths or []]
    if adjusted and missing_after_adjusted:
        classification = "confirmed_coinbase_data_hole_candidate"
    elif failed_validation.get("unexpected_count") and not failed_validation.get("missing_count"):
        classification = "deterministic_overlap_only"
    elif failed_validation.get("missing_count"):
        classification = "retryable_fetch_window_issue"
    else:
        classification = "unresolved_validation_blocker"
    return {
        "generated_at": now_iso(),
        "phase": "D6_known_gap_decision_tool_v1",
        "report_name": "chunk52_known_gap_decision_v1",
        "status": "chunk52_known_gap_decision_v1_ready",
        "chunk_id": chunk_id,
        "expected_start": int(expected_start),
        "expected_end_exclusive": int(expected_end_exclusive),
        "failed_candidate_path": str(assert_research_path(failed_candidate_path)),
        "adjusted_result_path": str(assert_research_path(adjusted_result_path)) if adjusted_result_path else "",
        "binance_reference_paths": reference_paths,
        "classification": classification,
        "coinbase_primary_dataset": True,
        "secondary_reference_only": True,
        "coinbase_cache_repair_allowed": False,
        "synthetic_candles_allowed": False,
        "binance_repair_allowed": False,
        "merge_allowed": False,
        "normal_backtests_released": False,
        "exploratory_only_allowed": classification == "confirmed_coinbase_data_hole_candidate",
        "failed_candidate_validation": failed_validation,
        "adjusted_fetch_result_summary": {
            "status": adjusted.get("status"),
            "stop_reason": adjusted.get("stop_reason"),
            "candidate_validation_status": adjusted_validation.get("status"),
            "missing_expected_count": missing_after_adjusted,
            "unexpected_starts_sample": adjusted_validation.get("unexpected_starts_sample", []),
        },
        "next_safe_command": "document_known_gap_policy_or_repeat_bounded_primary_source_review_before_resume",
        **_flags(),
    }


__all__ = ["build_known_gap_decision"]
