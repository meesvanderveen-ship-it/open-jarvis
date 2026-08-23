from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_baseline_backtest import build_phase_d6_baseline_backtest_report
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_24h_readiness_v11_research_only"
DEFAULT_EXPLORATORY_TICKERS = ["BTC-USDC", "ETH-USDC", "SOL-USDC"]
DEFAULT_BASELINES = ["buy_hold", "simple_ma"]


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


def load_report_content(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("d6_v11_source_must_be_object")
    content = loaded.get("content")
    return content if isinstance(content, dict) else loaded


def _rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(row) for row in report.get("rows") or [] if isinstance(row, dict)]


def _quality_index(quality_report: Dict[str, Any]) -> Dict[tuple[str, str], Dict[str, Any]]:
    return {
        (str(row.get("product_id") or "").upper(), str(row.get("timeframe") or "").upper()): row
        for row in _rows(quality_report)
    }


def build_recent_tail_refresh_plan(*, coverage_report: Dict[str, Any], quality_report: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    quality_rows = _rows(quality_report)
    stale_rows = [row for row in quality_rows if "stale_last_candle" in list(row.get("warnings") or [])]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "recent_tail_dataset_refresh_plan_v1",
        "status": "recent_tail_dataset_refresh_plan_ready",
        "as_of": as_of,
        "stale_row_count": len(stale_rows),
        "fatal_error_row_count": sum(1 for row in quality_rows if row.get("fatal_errors")),
        "gap_row_count": sum(1 for row in quality_rows if int(row.get("gap_count") or 0) > 0),
        "existing_fetcher_tail_capable": False,
        "fetch_executed": False,
        "reason_fetch_not_run": "existing_fetcher_selects_window_start_chunks",
        "safe_future_design": {
            "candidate_root_required": True,
            "candidate_root_pattern": "/tmp/d6_recent_tail_refresh_YYYYMMDD_roundN",
            "dry_run_first": True,
            "merge_after_candidate_success": True,
            "output_root": "research_data/coinbase/candles",
            "state_write_performed": False,
            "max_public_calls_per_run": 25,
        },
        "coverage_rows_seen": len(_rows(coverage_report)),
        **safety_flags(),
        "coinbase_public_market_data_call_performed": False,
    }


def _selected_coverage_rows(
    coverage_report: Dict[str, Any],
    quality_report: Dict[str, Any],
    tickers: Iterable[str],
) -> List[Dict[str, Any]]:
    allowed = {ticker.upper() for ticker in tickers}
    quality = _quality_index(quality_report)
    selected: List[Dict[str, Any]] = []
    for row in _rows(coverage_report):
        ticker = str(row.get("ticker") or "").upper()
        timeframe = str(row.get("timeframe") or "").upper()
        if ticker not in allowed or not row.get("cached_data_present"):
            continue
        q = quality.get((ticker, timeframe), {})
        if str(q.get("quality_class")) != "usable_with_warnings":
            continue
        selected.append(row)
    return sorted(selected, key=lambda row: (str(row.get("ticker")), str(row.get("timeframe"))))


def build_exploratory_backtest_result_bundle(
    *,
    coverage_report: Dict[str, Any],
    quality_report: Dict[str, Any],
    tickers: Iterable[str] = DEFAULT_EXPLORATORY_TICKERS,
    baselines: Iterable[str] = DEFAULT_BASELINES,
    as_of: str = "2026-06-01T00:00:00Z",
) -> Dict[str, Any]:
    selected_rows = _selected_coverage_rows(coverage_report, quality_report, tickers)
    results: List[Dict[str, Any]] = []
    for row in selected_rows:
        candles_path = str(row.get("cached_candles_path") or "")
        if not candles_path:
            continue
        for baseline in baselines:
            baseline_report = build_phase_d6_baseline_backtest_report(
                candles_path=candles_path,
                baseline=str(baseline),
                initial_quote="1000",
                fee_pct="0.0040",
            )
            results.append(
                {
                    "ticker": baseline_report["ticker"],
                    "timeframe": baseline_report["timeframe"],
                    "baseline_type": baseline_report["baseline_type"],
                    "mode": "exploratory_only",
                    "candle_count": baseline_report["candle_count"],
                    "gap_count": baseline_report["gap_count"],
                    "trades_count": baseline_report["trades_count"],
                    "round_trips": baseline_report["round_trips"],
                    "post_only_fill_model": baseline_report["post_only_fill_model"],
                    "warnings": sorted(set([*baseline_report.get("warnings", []), "dataset_quality_warning_only"])),
                    "result_payload": baseline_report,
                    "parameter_evidence_created": False,
                    "optimization_performed": False,
                    "ranking_performed": False,
                    "parameter_values_changed": False,
                    "learning_to_execution_enabled": False,
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_result_bundle_v1",
        "status": "exploratory_only_backtest_result_bundle_ready",
        "as_of": as_of,
        "selection_policy": {
            "tickers": list(tickers),
            "baselines": list(baselines),
            "bounded_subset": True,
            "reason": "prove_backtest_plumbing_without_parameter_evidence",
        },
        "selected_row_count": len(selected_rows),
        "result_count": len(results),
        "results": results,
        "normal_backtest_executed": False,
        "exploratory_backtest_executed": bool(results),
        "parameter_evidence_created": False,
        **safety_flags(),
    }


def build_preflight_runner_report(
    *,
    local_safety: Dict[str, Any],
    readiness_report: Dict[str, Any],
    as_of: str,
) -> Dict[str, Any]:
    open_orders = int(((local_safety.get("open_orders") or {}).get("summary") or {}).get("open_orders") or 0)
    d3_status = (local_safety.get("d3") or {}).get("status")
    audit_text = str(local_safety.get("function_audit_stdout") or "")
    state_hashes = dict(local_safety.get("state_hashes") or {})
    preflight_pass = open_orders == 0 and d3_status == "d3_no_manageable_open_position" and "Status:    ok_observe_only" in audit_text
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_runner_v1",
        "status": "24h_live_test_preflight_runner_ready",
        "as_of": as_of,
        "preflight_result": "pass_local_non_live_checks" if preflight_pass else "blocked",
        "observed_local_checks": {
            "open_orders": open_orders,
            "d3_status": d3_status,
            "function_audit_ok_observe_only": "Status:    ok_observe_only" in audit_text,
            "state_hashes": state_hashes,
        },
        "route_matrix": {
            "btc_usdc_only": {
                "status": "ack_gated_after_fresh_preflight",
                "max_notional_usdc": "10",
                "max_live_order_count": 1,
                "allowed_tickers": ["BTC-USDC"],
            },
            "staged_non_btc_pilot": {
                "status": "blocked_until_separate_non_btc_design",
                "allowed_tickers": [],
            },
            "all_ticker_24h": {
                "status": "blocked",
                "allowed_tickers": [],
            },
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
            "missing_exact_future_ack",
            "unclear_product_rules_or_balance",
        ],
        "source_readiness_status": readiness_report.get("status"),
        **safety_flags(),
    }


def build_readiness_master_v11(
    *,
    tail_plan: Dict[str, Any],
    exploratory_bundle: Dict[str, Any],
    preflight_report: Dict[str, Any],
    as_of: str,
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v11",
        "status": "24h_readiness_master_packet_v11_ready",
        "as_of": as_of,
        "coverage_status": "complete_required_cached_rows",
        "dataset_freshness_status": "tail_refresh_planned_not_run",
        "exploratory_backtest_status": "bounded_subset_completed" if exploratory_bundle.get("result_count") else "not_run",
        "preflight_runner_status": preflight_report.get("preflight_result"),
        "btc_usdc_only_24h_status": "ack_gated_after_fresh_preflight",
        "staged_non_btc_status": "blocked_until_separate_design",
        "all_ticker_24h_status": "blocked",
        "remaining_blockers": [
            "dataset_quality_warning_only_staleness",
            "normal_backtests_not_run",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "evidence": {
            "tail_plan_status": tail_plan.get("status"),
            "exploratory_result_count": exploratory_bundle.get("result_count"),
            "preflight_result": preflight_report.get("preflight_result"),
        },
        **safety_flags(),
    }


__all__ = [
    "DEFAULT_BASELINES",
    "DEFAULT_EXPLORATORY_TICKERS",
    "PHASE",
    "build_exploratory_backtest_result_bundle",
    "build_preflight_runner_report",
    "build_readiness_master_v11",
    "build_recent_tail_refresh_plan",
    "load_report_content",
    "safety_flags",
]
