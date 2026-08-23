from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
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
        "config_mutation_performed": False,
        "parameter_values_changed": False,
        "parameter_search_performed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_live_instructions": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "live_recommendation": False,
    }


def _content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    return dict(loaded.get("content") or loaded)


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _starts(path: str | Path) -> List[int]:
    rows = _load_rows(path)
    out: List[int] = []
    for row in rows:
        try:
            out.append(int(row["start"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(out))


def build_known_gap_policy_review(
    *,
    decision_report_path: str | Path,
    existing_cache_path: str | Path,
    failed_candidate_path: str | Path,
    adjusted_result_path: str | Path,
    binance_reference_paths: Iterable[str | Path] | None = None,
) -> Dict[str, Any]:
    decision = _content(decision_report_path)
    adjusted = _content(adjusted_result_path)
    failed_validation = dict(decision.get("failed_candidate_validation") or {})
    adjusted_validation = dict(adjusted.get("candidate_validation") or decision.get("adjusted_fetch_result_summary") or {})
    missing = list(failed_validation.get("issues", [{}])[0].get("starts_sample", [])) if failed_validation.get("issues") else []
    if not missing:
        missing = list((decision.get("failed_candidate_validation") or {}).get("missing_expected_starts_sample") or [])
    if not missing:
        missing = [1761408000, 1761411600, 1761415200, 1761418800, 1761422400]
    existing = set(_starts(existing_cache_path))
    failed_starts = set(_starts(failed_candidate_path))
    binance_refs = [str(assert_research_path(path)) for path in binance_reference_paths or []]
    missing_in_existing = [start for start in missing if start not in existing]
    missing_in_failed_candidate = [start for start in missing if start not in failed_starts]
    classification = "confirmed_primary_source_data_hole" if decision.get("classification") == "confirmed_coinbase_data_hole_candidate" else "unresolved_validation_blocker"
    allows_exploratory = classification == "confirmed_primary_source_data_hole"
    return {
        "generated_at": now_iso(),
        "phase": "D6_known_gap_policy_review_v1",
        "report_name": "chunk52_known_gap_policy_review_v1",
        "status": "chunk52_known_gap_policy_review_v1_ready",
        "chunk_id": decision.get("chunk_id", "BTCUSDC-1H-gap01:chunk52"),
        "classification": classification,
        "missing_coinbase_starts": missing,
        "missing_starts_absent_from_existing_cache": missing_in_existing,
        "missing_starts_absent_from_failed_candidate": missing_in_failed_candidate,
        "previous_retry_fetch_evidence": {
            "decision_report": str(assert_research_path(decision_report_path)),
            "adjusted_result": str(assert_research_path(adjusted_result_path)),
            "adjusted_status": adjusted.get("status"),
            "adjusted_stop_reason": adjusted.get("stop_reason"),
            "adjusted_candidate_validation": adjusted_validation,
        },
        "candidate_validation_outcome": {
            "failed_candidate_path": str(assert_research_path(failed_candidate_path)),
            "blocks_merge": True,
            "failed_candidate_missing_count": len(missing_in_failed_candidate),
            "failed_candidate_overlap_count": failed_validation.get("overlap_count"),
        },
        "secondary_reference_context": {
            "binance_reference_paths": binance_refs,
            "binance_can_repair_coinbase_cache": False,
            "binance_can_release_normal_backtest": False,
        },
        "policy_decision": {
            "unresolved_validation_blocker": classification == "unresolved_validation_blocker",
            "confirmed_primary_source_data_hole": classification == "confirmed_primary_source_data_hole",
            "retryable_fetch_window_issue": False,
            "acceptable_known_gap_for_exploratory_only": allows_exploratory,
            "unacceptable_for_normal_backtests": True,
            "blocks_merge": True,
            "blocks_normal_backtest": True,
            "allows_exploratory_only": allows_exploratory,
            "allows_chunk53_continuation": allows_exploratory,
            "requires_human_ack": True,
            "requires_future_revisit": True,
        },
        "why_no_synthetic_candle": "Synthetic OHLCV would mutate primary-source evidence and hide an exchange data-quality issue.",
        "why_binance_cannot_repair": "Binance is secondary/reference-only and cannot be stored as Coinbase raw cache or release normal gates.",
        "exact_next_safe_command": "operator_ack_known_gap_policy_then_dry_run_chunk53_plus_with_historical_downloader",
        **_flags(),
    }


__all__ = ["build_known_gap_policy_review"]
