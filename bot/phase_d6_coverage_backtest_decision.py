from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_coverage_backtest_decision_v1"


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
        "normal_backtest_executed": False,
        "exploratory_backtest_executed": False,
    }


def _load_report(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_decision_report_source_must_be_object")
    content = loaded.get("content")
    return content if isinstance(content, dict) else loaded


def _coverage_rows(coverage_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = coverage_report.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _quality_rows(quality_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = quality_report.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _quality_by_row(quality_report: Dict[str, Any]) -> Dict[tuple[str, str], Dict[str, Any]]:
    indexed: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in _quality_rows(quality_report):
        product = str(row.get("product_id") or row.get("ticker") or "").upper()
        timeframe = str(row.get("timeframe") or "").upper()
        if product and timeframe:
            indexed[(product, timeframe)] = row
    return indexed


def _command_plan(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    commands: List[Dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or row.get("product_id") or "").upper()
        timeframe = str(row.get("timeframe") or "").upper()
        candles_path = str(row.get("cached_candles_path") or row.get("candles_path") or "")
        if not ticker or not timeframe or not candles_path:
            continue
        stem = ticker.lower().replace("-", "_")
        tf = timeframe.lower()
        for baseline in ("buy_hold", "simple_ma"):
            commands.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "baseline": baseline,
                    "mode": "exploratory_only",
                    "run_now": False,
                    "blocked_reason": "dataset_quality_warning_only",
                    "command": (
                        ".venv/bin/python tools/run_phase_d6_baseline_backtest.py "
                        f"--candles {candles_path} --baseline {baseline} "
                        f"--output reports/d6/exploratory-baselines/{stem}-{tf}-{baseline}-20260601.json"
                    ),
                    "output_path": f"reports/d6/exploratory-baselines/{stem}-{tf}-{baseline}-20260601.json",
                    "state_write_performed": False,
                    "parameter_values_changed": False,
                    "optimization_performed": False,
                    "learning_to_execution_enabled": False,
                }
            )
    return commands


def build_coverage_backtest_decision(
    *,
    coverage_report: Dict[str, Any],
    quality_report: Dict[str, Any],
    expansion_report: Dict[str, Any] | None = None,
    as_of: str = "2026-06-01T00:00:00Z",
) -> Dict[str, Any]:
    rows = _coverage_rows(coverage_report)
    quality_index = _quality_by_row(quality_report)
    missing_rows = [row for row in rows if not row.get("cached_data_present")]
    cached_rows = [row for row in rows if row.get("cached_data_present")]
    warning_rows = [
        row
        for row in cached_rows
        if str((quality_index.get((str(row.get("ticker", "")).upper(), str(row.get("timeframe", "")).upper())) or {}).get("quality_class"))
        == "usable_with_warnings"
    ]
    good_rows = [
        row
        for row in cached_rows
        if str((quality_index.get((str(row.get("ticker", "")).upper(), str(row.get("timeframe", "")).upper())) or {}).get("quality_class"))
        == "good"
    ]
    all_cached_rows_warning_only = bool(cached_rows) and len(warning_rows) == len(cached_rows)
    command_plan = _command_plan(cached_rows)
    xrp_1h_row = next(
        (
            row
            for row in cached_rows
            if str(row.get("ticker")).upper() == "XRP-USDC" and str(row.get("timeframe")).upper() == "1H"
        ),
        None,
    )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "coverage_backtest_decision_v1",
        "status": "coverage_backtest_decision_ready",
        "as_of": as_of,
        "coverage_completeness": {
            "configured_ticker_count": coverage_report.get("configured_ticker_count"),
            "required_row_count": len(rows),
            "cached_file_count": len(cached_rows),
            "missing_row_count": len(missing_rows),
            "complete_required_rows": len(rows) > 0 and len(missing_rows) == 0,
        },
        "xrp_usdc_1h_diagnostic": {
            "status": "resolved" if xrp_1h_row else "still_missing",
            "diagnostic_summary": [
                "Earlier small 3y chunk windows reached an old empty interval.",
                "Bounded later-window checks returned XRP-USDC 1H candles.",
                "A bounded 3y max_chunks=25 candidate fetch produced the merged cached 1H row.",
            ],
            "merged_candle_count": xrp_1h_row.get("candle_count") if xrp_1h_row else 0,
            "coinbase_endpoint_scope": "public_market_data_candles_only",
            "state_write_performed": False,
        },
        "dataset_quality_decision": {
            "quality_report_count": (quality_report.get("summary") or {}).get("quality_report_count", len(_quality_rows(quality_report))),
            "good_count": len(good_rows),
            "warning_count": len(warning_rows),
            "all_cached_rows_warning_only": all_cached_rows_warning_only,
            "normal_backtests_as_parameter_evidence": False,
        },
        "backtest_decision": {
            "normal_backtests_deferred": all_cached_rows_warning_only,
            "exploratory_only_scaffold_ready": bool(command_plan),
            "normal_backtest_executed": False,
            "exploratory_backtest_executed": False,
            "parameter_evidence_created": False,
            "blocked_reason": "dataset_quality_warning_only" if all_cached_rows_warning_only else "",
        },
        "exploratory_only_command_plan": command_plan,
        "readiness_update": {
            "btc_usdc_only_24h_route_status": "ack_gated_with_warning_quality_research_data",
            "all_ticker_24h_route_status": "blocked_until_dataset_quality_and_non_btc_lifecycle_evidence_are_stronger",
            "parameter_review_approved": False,
            "parameter_values_changed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "learning_to_execution_enabled": False,
        },
        "source_report_status": {
            "coverage_status": coverage_report.get("status"),
            "quality_status": quality_report.get("status"),
            "expansion_status": (expansion_report or {}).get("status"),
        },
        **safety_flags(),
    }


def build_coverage_backtest_decision_from_paths(
    *,
    coverage_report_path: str | Path,
    quality_report_path: str | Path,
    expansion_report_path: str | Path | None = None,
    as_of: str = "2026-06-01T00:00:00Z",
) -> Dict[str, Any]:
    return build_coverage_backtest_decision(
        coverage_report=_load_report(coverage_report_path),
        quality_report=_load_report(quality_report_path),
        expansion_report=_load_report(expansion_report_path) if expansion_report_path else None,
        as_of=as_of,
    )


__all__ = [
    "PHASE",
    "build_coverage_backtest_decision",
    "build_coverage_backtest_decision_from_paths",
    "safety_flags",
]
