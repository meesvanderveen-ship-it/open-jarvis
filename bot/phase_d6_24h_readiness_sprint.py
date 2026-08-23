from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_24h_readiness_research_sprint_v1"


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


def load_report_content(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_24h_sprint_source_must_be_object")
    content = loaded.get("content")
    return content if isinstance(content, dict) else loaded


def _quality_rows(quality_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(row) for row in quality_report.get("rows") or [] if isinstance(row, dict)]


def _coverage_rows(coverage_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(row) for row in coverage_report.get("rows") or [] if isinstance(row, dict)]


def _group_counts(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[str(row.get(key) or "unknown")] += 1
    return dict(sorted(counts.items()))


def build_dataset_quality_warning_diagnostic(*, quality_report: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    rows = _quality_rows(quality_report)
    warning_counts: Counter[str] = Counter()
    by_timeframe: dict[str, Counter[str]] = defaultdict(Counter)
    by_ticker: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        warnings = list(row.get("warnings") or [])
        if not warnings:
            warning_counts["none"] += 1
        for warning in warnings:
            warning_counts[str(warning)] += 1
            by_timeframe[str(row.get("timeframe") or "unknown")][str(warning)] += 1
            by_ticker[str(row.get("product_id") or "unknown")][str(warning)] += 1
    fatal_rows = [row for row in rows if row.get("fatal_errors")]
    gap_rows = [row for row in rows if int(row.get("gap_count") or 0) > 0]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "dataset_quality_warning_diagnostic_v1",
        "status": "dataset_quality_warning_diagnostic_ready",
        "as_of": as_of,
        "quality_report_count": len(rows),
        "quality_class_counts": _group_counts(rows, "quality_class"),
        "warning_counts": dict(sorted(warning_counts.items())),
        "warning_counts_by_timeframe": {key: dict(sorted(value.items())) for key, value in sorted(by_timeframe.items())},
        "warning_counts_by_ticker": {key: dict(sorted(value.items())) for key, value in sorted(by_ticker.items())},
        "fatal_error_row_count": len(fatal_rows),
        "gap_row_count": len(gap_rows),
        "diagnostic_conclusion": {
            "dominant_warning": warning_counts.most_common(1)[0][0] if warning_counts else "",
            "invalid_rows_present": bool(fatal_rows),
            "gap_rows_present": bool(gap_rows),
            "normal_backtests_as_parameter_evidence": False,
            "next_research_action": "refresh_recent_candle_tail_or_keep_exploratory_only",
        },
        "sample_rows": rows[:5],
        **safety_flags(),
    }


def _baseline_commands(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    ticker = str(row.get("ticker") or row.get("product_id") or "").upper()
    timeframe = str(row.get("timeframe") or "").upper()
    candles_path = str(row.get("cached_candles_path") or row.get("candles_path") or "")
    if not ticker or not timeframe or not candles_path:
        return []
    stem = ticker.lower().replace("-", "_")
    tf = timeframe.lower()
    out: List[Dict[str, Any]] = []
    for baseline in ("buy_hold", "simple_ma"):
        output_path = f"reports/d6/exploratory-baselines/{stem}-{tf}-{baseline}-20260601.json"
        out.append(
            {
                "ticker": ticker,
                "timeframe": timeframe,
                "baseline": baseline,
                "mode": "exploratory_only",
                "run_now": False,
                "blocked_reason": "dataset_quality_warning_only",
                "command": (
                    ".venv/bin/python tools/run_phase_d6_baseline_backtest.py "
                    f"--candles {candles_path} --baseline {baseline} --output {output_path}"
                ),
                "output_path": output_path,
                "state_write_performed": False,
                "parameter_values_changed": False,
                "optimization_performed": False,
                "learning_to_execution_enabled": False,
            }
        )
    return out


def build_exploratory_backtest_readiness(*, coverage_report: Dict[str, Any], quality_report: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    coverage_rows = _coverage_rows(coverage_report)
    quality_rows = _quality_rows(quality_report)
    quality_by_key = {
        (str(row.get("product_id") or "").upper(), str(row.get("timeframe") or "").upper()): row for row in quality_rows
    }
    cached_rows = [row for row in coverage_rows if row.get("cached_data_present")]
    missing_rows = [row for row in coverage_rows if not row.get("cached_data_present")]
    warning_only_rows = []
    eligible_plan_rows = []
    for row in cached_rows:
        key = (str(row.get("ticker") or "").upper(), str(row.get("timeframe") or "").upper())
        quality = quality_by_key.get(key, {})
        if str(quality.get("quality_class")) == "usable_with_warnings":
            warning_only_rows.append(row)
            eligible_plan_rows.append(row)
    commands = [command for row in eligible_plan_rows for command in _baseline_commands(row)]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_readiness_v1",
        "status": "exploratory_only_backtest_readiness_ready",
        "as_of": as_of,
        "cached_row_count": len(cached_rows),
        "missing_row_count": len(missing_rows),
        "warning_only_row_count": len(warning_only_rows),
        "normal_backtests_deferred": True,
        "exploratory_only_command_count": len(commands),
        "exploratory_only_command_plan": commands,
        "execution_policy": {
            "run_commands_now": False,
            "normal_backtest_executed": False,
            "exploratory_backtest_executed": False,
            "parameter_evidence_created": False,
            "reason": "all_cached_rows_warning_only",
        },
        **safety_flags(),
    }


def build_24h_preflight_architecture(*, coverage_report: Dict[str, Any], quality_report: Dict[str, Any], readiness_report: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    coverage_rows = _coverage_rows(coverage_report)
    quality_rows = _quality_rows(quality_report)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_architecture_v1",
        "status": "24h_live_test_preflight_architecture_ready",
        "as_of": as_of,
        "scope_routes": {
            "btc_usdc_only": {
                "status": "ack_gated",
                "allowed_scope_if_later_approved": {
                    "ticker": "BTC-USDC",
                    "max_live_order_count": 1,
                    "max_notional_usdc": "10",
                    "all_ticker_scope": False,
                },
                "required_future_acks": [
                    "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
                    "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
                    "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
                ],
                "stop_conditions": [
                    "unexpected_open_order",
                    "active_d3_exit",
                    "function_audit_not_observe_only",
                    "state_hash_drift",
                    "product_or_balance_preflight_unclear",
                    "operator_ack_missing",
                ],
            },
            "staged_non_btc_pilot": {
                "status": "blocked_until_separate_design",
                "reason": "non_btc_live_lifecycle_evidence_missing",
            },
            "all_ticker_24h": {
                "status": "blocked",
                "reason": "warning_only_dataset_quality_and_missing_non_btc_live_lifecycle_evidence",
            },
        },
        "telemetry_plan": {
            "local_safety": ["open_orders", "open_d3_exit", "function_preservation_audit", "state_hashes"],
            "order_lifecycle": ["client_order_id", "exchange_order_id", "status", "fills", "fees", "timestamps"],
            "research_evidence": ["order_events", "d5_rows", "d6_governance_rows", "post_run_readiness_report"],
        },
        "coverage_summary": {
            "required_rows": len(coverage_rows),
            "cached_rows": sum(1 for row in coverage_rows if row.get("cached_data_present")),
            "quality_rows": len(quality_rows),
            "warning_only_rows": sum(1 for row in quality_rows if row.get("quality_class") == "usable_with_warnings"),
        },
        "source_readiness_status": readiness_report.get("status"),
        **safety_flags(),
    }


def build_24h_readiness_master_v10(
    *,
    warning_diagnostic: Dict[str, Any],
    exploratory_readiness: Dict[str, Any],
    preflight_architecture: Dict[str, Any],
    as_of: str,
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v10",
        "status": "24h_readiness_master_packet_v10_ready",
        "as_of": as_of,
        "coverage_status": "complete_required_cached_rows",
        "dataset_quality_status": "warning_only",
        "normal_backtest_status": "deferred",
        "exploratory_only_status": "scaffold_ready",
        "btc_usdc_only_24h_status": preflight_architecture["scope_routes"]["btc_usdc_only"]["status"],
        "all_ticker_24h_status": preflight_architecture["scope_routes"]["all_ticker_24h"]["status"],
        "blockers": [
            "dataset_quality_warning_only",
            "normal_backtests_not_run",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "evidence": {
            "warning_diagnostic_status": warning_diagnostic.get("status"),
            "exploratory_readiness_status": exploratory_readiness.get("status"),
            "preflight_architecture_status": preflight_architecture.get("status"),
            "exploratory_only_command_count": exploratory_readiness.get("exploratory_only_command_count"),
        },
        **safety_flags(),
    }


__all__ = [
    "PHASE",
    "build_24h_preflight_architecture",
    "build_24h_readiness_master_v10",
    "build_dataset_quality_warning_diagnostic",
    "build_exploratory_backtest_readiness",
    "load_report_content",
    "safety_flags",
]
