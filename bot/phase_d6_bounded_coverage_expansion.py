from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_bounded_fetch_postprocess import (
    build_dataset_coverage_refresh,
    build_post_fetch_dataset_quality_summary,
)
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_bounded_candle_coverage_expansion_v1"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"


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
    }


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    p = assert_research_path(path)
    if not p.exists():
        return []
    payload = json.loads(p.read_text(encoding="utf-8"))
    return list(payload) if isinstance(payload, list) else []


def _write_rows(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    p = assert_research_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dedup_sort(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_start: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            start = int(row.get("start"))
        except Exception:
            continue
        by_start[start] = dict(row)
    return [by_start[start] for start in sorted(by_start)]


def merge_candidate_candles(*, existing_path: str | Path, candidate_path: str | Path) -> Dict[str, Any]:
    existing = _load_rows(existing_path)
    candidate = _load_rows(candidate_path)
    merged = _dedup_sort([*existing, *candidate])
    updated = len(merged) > len(existing)
    if updated:
        _write_rows(existing_path, merged)
    return {
        "existing_path": str(existing_path),
        "candidate_path": str(candidate_path),
        "before_count": len(existing),
        "candidate_count": len(candidate),
        "after_count": len(merged),
        "updated": updated,
        "state_write_performed": False,
    }


def discover_candidate_candle_pairs(*, candidate_root: str | Path) -> List[Dict[str, str]]:
    root = assert_research_path(candidate_root)
    if not root.exists():
        return []
    pairs: List[Dict[str, str]] = []
    for candidate in sorted(root.glob("product=*/timeframe=*/study_window=*.json")):
        product = candidate.parent.parent.name
        timeframe = candidate.parent.name
        study_window = candidate.name
        existing = Path("research_data/coinbase/candles") / product / timeframe / study_window
        pairs.append(
            {
                "product": product.removeprefix("product="),
                "timeframe": timeframe.removeprefix("timeframe="),
                "study_window": study_window.removeprefix("study_window=").removesuffix(".json"),
                "candidate_path": str(candidate),
                "existing_path": str(existing),
            }
        )
    return pairs


def build_coverage_expansion_result(
    *,
    merge_results: Iterable[Dict[str, Any]],
    max_chunks: int,
    public_call_count: int,
    sandbox_errors: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    rows = list(merge_results)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "bounded_candle_coverage_expansion_result_v1",
        "status": "bounded_candle_coverage_expansion_ready",
        "required_ack": DATA_FETCH_ACK,
        "ack_present": True,
        "fetched_rows": rows,
        "created_or_updated_files": sorted(row["existing_path"] for row in rows if row.get("updated")),
        "max_chunks_used": max_chunks,
        "coinbase_public_market_data_call_count": public_call_count,
        "sandbox_errors_before_escalation": list(sandbox_errors or []),
        "remaining_boundaries_closed": [
            "no_live_order_action",
            "no_account_or_order_endpoint",
            "no_state_write",
            "no_config_or_parameter_mutation",
            "no_learning_to_execution",
        ],
        **safety_flags(),
    }


def build_coverage_refresh_v2(*, config_text: str, candle_paths: Iterable[str | Path], as_of: str) -> Dict[str, Any]:
    report = build_dataset_coverage_refresh(config_text=config_text, candle_paths=candle_paths, as_of=as_of)
    report["phase"] = PHASE
    report["report_name"] = "multi_ticker_dataset_coverage_plan_refresh_v2"
    report["status"] = "multi_ticker_dataset_coverage_plan_refresh_v2_ready"
    return report


def build_quality_summary_v2(*, candle_paths: Iterable[str | Path], as_of: str) -> Dict[str, Any]:
    report = build_post_fetch_dataset_quality_summary(candle_paths=candle_paths, as_of=as_of)
    report["phase"] = PHASE
    report["report_name"] = "post_fetch_dataset_quality_summary_v2"
    report["status"] = "post_fetch_dataset_quality_summary_v2_ready"
    report["btc_usdc_cached_baseline_decision"] = "defer_cached_backtest_until_coverage_is_less_stale_or_operator_accepts_warning_only_research"
    return report


__all__ = [
    "build_coverage_expansion_result",
    "build_coverage_refresh_v2",
    "build_quality_summary_v2",
    "discover_candidate_candle_pairs",
    "merge_candidate_candles",
    "safety_flags",
]
