from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_multi_ticker_backlearning_readiness import build_multi_ticker_dataset_coverage_plan


PHASE = "D6_bounded_fetch_postprocess_v1"
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


def _load_candle_count(path: str | Path) -> int:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _is_state_path(path: str | Path) -> bool:
    return "state" in {part.lower() for part in Path(path).parts}


def build_bounded_fetch_result_report(
    *,
    requested_rows: Iterable[Dict[str, Any]],
    max_chunks: int,
    sandbox_errors: Iterable[Dict[str, Any]] | None = None,
    escalated_fetch_performed: bool = True,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    created_files: List[str] = []
    warnings: List[str] = []
    for row in requested_rows:
        path = str(row["output_path"])
        count = _load_candle_count(path)
        exists = Path(path).is_file()
        if exists:
            created_files.append(path)
        if _is_state_path(path):
            warnings.append(f"state_path_detected:{path}")
        rows.append(
            {
                "ticker": row["ticker"],
                "timeframe": row["timeframe"],
                "requested_chunks": int(row.get("requested_chunks") or max_chunks),
                "chunks_fetched": int(row.get("chunks_fetched") or (max_chunks if exists and count else 0)),
                "candle_count": count,
                "output_path": path,
                "file_exists": exists,
                "state_path": _is_state_path(path),
                "errors": list(row.get("errors") or []),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "bounded_multi_ticker_candle_fetch_result_v1",
        "status": "bounded_research_fetch_completed_with_data" if created_files else "bounded_research_fetch_no_data",
        "required_ack": DATA_FETCH_ACK,
        "ack_present": True,
        "requested_rows": rows,
        "actually_fetched_rows": [row for row in rows if row["candle_count"] > 0],
        "created_or_updated_files": sorted(created_files),
        "skipped_rows": [],
        "max_chunks_used": max_chunks,
        "coinbase_public_market_data_call_count": sum(int(row["chunks_fetched"]) for row in rows),
        "sandbox_errors_before_escalation": list(sandbox_errors or []),
        "escalated_network_fetch_performed": bool(escalated_fetch_performed),
        "warnings": warnings,
        **safety_flags(),
    }


def build_dataset_coverage_refresh(
    *,
    config_text: str,
    candle_paths: Iterable[str | Path],
    as_of: str,
) -> Dict[str, Any]:
    report = build_multi_ticker_dataset_coverage_plan(
        config_text=config_text,
        candle_paths=candle_paths,
        as_of=as_of,
    )
    report["report_name"] = "multi_ticker_dataset_coverage_plan_refresh_v1"
    report["status"] = "multi_ticker_dataset_coverage_plan_refresh_ready"
    report["phase"] = PHASE
    return report


def build_post_fetch_dataset_quality_summary(
    *,
    candle_paths: Iterable[str | Path],
    as_of: str,
) -> Dict[str, Any]:
    quality_rows = []
    for raw_path in sorted(str(path) for path in candle_paths):
        if _is_state_path(raw_path):
            continue
        quality = build_phase_d6_dataset_quality_report(candles_path=raw_path, as_of=as_of)
        quality_rows.append(
            {
                "candles_path": raw_path,
                "product_id": quality.get("product_id"),
                "timeframe": quality.get("timeframe"),
                "status": quality.get("status"),
                "quality_class": quality.get("quality_class"),
                "candle_count": quality.get("candle_count"),
                "gap_count": quality.get("gap_count"),
                "warnings": list(quality.get("warnings") or []),
                "fatal_errors": list(quality.get("fatal_errors") or []),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "post_fetch_dataset_quality_summary_v1",
        "status": "post_fetch_dataset_quality_summary_ready",
        "rows": quality_rows,
        "summary": {
            "quality_report_count": len(quality_rows),
            "good_count": sum(1 for row in quality_rows if row.get("quality_class") == "good"),
            "warning_count": sum(1 for row in quality_rows if row.get("warnings")),
            "invalid_count": sum(1 for row in quality_rows if row.get("quality_class") == "invalid"),
        },
        **safety_flags(),
    }


__all__ = [
    "build_bounded_fetch_result_report",
    "build_dataset_coverage_refresh",
    "build_post_fetch_dataset_quality_summary",
    "safety_flags",
]
