from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report


D6_DATASET_QUALITY_AGGREGATE_PHASE = "D6_dataset_quality_aggregate_v1"
QUALITY_CLASSES = ["good", "usable_with_warnings", "poor", "invalid"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_candle_paths(paths: Iterable[str | Path]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = assert_research_path(raw)
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    if not out:
        raise ValueError("d6_dataset_quality_aggregate_requires_at_least_one_candle_file")
    return out


def _compact_quality(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "candles_path": report["candles_path"],
        "product_id": report.get("product_id"),
        "timeframe": report.get("timeframe"),
        "raw_row_count": report.get("raw_row_count"),
        "candle_count": report.get("candle_count"),
        "valid_candle_row_count": report.get("valid_candle_row_count"),
        "first_candle_start": report.get("first_candle_start"),
        "last_candle_start": report.get("last_candle_start"),
        "observed_span_seconds": report.get("observed_span_seconds"),
        "observed_span_days": report.get("observed_span_days"),
        "expected_candle_count": report.get("expected_candle_count"),
        "missing_candle_estimate": report.get("missing_candle_estimate"),
        "gap_count": report.get("gap_count"),
        "duplicate_count": report.get("duplicate_count"),
        "non_monotonic_count": report.get("non_monotonic_count"),
        "invalid_ohlcv_count": report.get("invalid_ohlcv_count"),
        "quality_class": report.get("quality_class"),
        "warnings": list(report.get("warnings") or []),
        "fatal_errors": list(report.get("fatal_errors") or []),
    }


def _summary(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    quality_counts = {name: 0 for name in QUALITY_CLASSES}
    warning_counts: Dict[str, int] = {}
    fatal_error_counts: Dict[str, int] = {}
    total_missing = 0
    total_gaps = 0
    total_duplicates = 0
    total_invalid_ohlcv = 0
    blockers: List[str] = []

    for report in reports:
        quality = str(report.get("quality_class") or "invalid")
        if quality not in quality_counts:
            quality_counts[quality] = 0
        quality_counts[quality] += 1
        if quality in {"poor", "invalid"}:
            blockers.append(f"{quality}_dataset:{report.get('candles_path')}")
        for warning in report.get("warnings") or []:
            warning_counts[str(warning)] = warning_counts.get(str(warning), 0) + 1
        for error in report.get("fatal_errors") or []:
            fatal_error_counts[str(error)] = fatal_error_counts.get(str(error), 0) + 1
        total_missing += int(report.get("missing_candle_estimate") or 0)
        total_gaps += int(report.get("gap_count") or 0)
        total_duplicates += int(report.get("duplicate_count") or 0)
        total_invalid_ohlcv += int(report.get("invalid_ohlcv_count") or 0)

    aggregate_quality = "good"
    if quality_counts.get("invalid", 0):
        aggregate_quality = "invalid"
    elif quality_counts.get("poor", 0):
        aggregate_quality = "poor"
    elif any(count for name, count in quality_counts.items() if name != "good"):
        aggregate_quality = "usable_with_warnings"

    return {
        "file_count": len(reports),
        "quality_counts": quality_counts,
        "aggregate_quality_class": aggregate_quality,
        "tickers": sorted({str(r.get("product_id")) for r in reports if r.get("product_id")}),
        "timeframes": sorted({str(r.get("timeframe")) for r in reports if r.get("timeframe")}),
        "total_missing_candle_estimate": total_missing,
        "total_gap_count": total_gaps,
        "total_duplicate_count": total_duplicates,
        "total_invalid_ohlcv_count": total_invalid_ohlcv,
        "warning_counts": warning_counts,
        "fatal_error_counts": fatal_error_counts,
        "blockers": blockers,
        "ready_for_baseline_bundle": not blockers,
        "ready_for_walk_forward_scaffold": not blockers and aggregate_quality in {"good", "usable_with_warnings"},
    }


def build_phase_d6_dataset_quality_aggregate_report(
    *,
    candle_paths: Iterable[str | Path],
    as_of: Any = None,
) -> Dict[str, Any]:
    paths = normalize_candle_paths(candle_paths)
    full_reports = [
        build_phase_d6_dataset_quality_report(candles_path=path, as_of=as_of)
        for path in paths
    ]
    compact_reports = [_compact_quality(report) for report in full_reports]
    warnings = [
        "research_dataset_quality_aggregate_only",
        "not_backtest",
        "not_parameter_search",
        "not_optimization",
    ]
    summary = _summary(compact_reports)
    if summary["blockers"]:
        warnings.append("poor_or_invalid_dataset_present")

    return {
        "generated_at": _now_iso(),
        "phase": D6_DATASET_QUALITY_AGGREGATE_PHASE,
        "status": "d6_dataset_quality_aggregate_ready",
        "as_of": str(as_of or ""),
        "candle_paths": paths,
        "summary": summary,
        "reports": compact_reports,
        "warnings": warnings,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "parameter_search_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def aggregate_to_markdown(report: Dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    lines = [
        "# D.6 Dataset Quality Aggregate",
        "",
        f"- generated_at: `{report.get('generated_at', '')}`",
        f"- file_count: `{summary.get('file_count', 0)}`",
        f"- aggregate_quality_class: `{summary.get('aggregate_quality_class', '')}`",
        f"- total_gap_count: `{summary.get('total_gap_count', 0)}`",
        f"- total_missing_candle_estimate: `{summary.get('total_missing_candle_estimate', 0)}`",
        f"- ready_for_baseline_bundle: `{summary.get('ready_for_baseline_bundle')}`",
        f"- ready_for_walk_forward_scaffold: `{summary.get('ready_for_walk_forward_scaffold')}`",
        "",
        "| product | timeframe | quality | candles | expected | missing | gaps | duplicates | invalid_ohlcv |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("reports") or []:
        lines.append(
            "| {product_id} | {timeframe} | {quality_class} | {candle_count} | {expected_candle_count} | {missing_candle_estimate} | {gap_count} | {duplicate_count} | {invalid_ohlcv_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "Safety:",
            "",
            f"- research_only: `{report.get('research_only')}`",
            f"- no_coinbase_call: `{report.get('no_coinbase_call')}`",
            f"- no_live_action: `{report.get('no_live_action')}`",
            f"- state_write_performed: `{report.get('state_write_performed')}`",
            f"- no_optimization: `{report.get('no_optimization')}`",
            f"- parameter_change_allowed: `{report.get('parameter_change_allowed')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_aggregate(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_aggregate(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(aggregate_to_markdown(report), encoding="utf-8")
    return path


__all__ = [
    "D6_DATASET_QUALITY_AGGREGATE_PHASE",
    "build_phase_d6_dataset_quality_aggregate_report",
    "aggregate_to_markdown",
    "write_json_aggregate",
    "write_markdown_aggregate",
    "normalize_candle_paths",
]
