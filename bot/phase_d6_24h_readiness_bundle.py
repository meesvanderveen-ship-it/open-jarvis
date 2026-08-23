from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_cost_aware_baseline_bundle import build_phase_d6_cost_aware_baseline_bundle
from bot.phase_d6_data_coverage import D6_DEFAULT_TICKERS, D6_REQUIRED_TIMEFRAMES, build_phase_d6_data_coverage_report
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_workflow_ticker_audit import extract_default_allowed_tickers


D6_24H_READINESS_BUNDLE_PHASE = "D6_24h_live_test_readiness_bundle_v1"
DEFAULT_LIVE_TEST_TICKER = "BTC-USDC"
DEFAULT_AS_OF = "2026-06-01T00:00:00Z"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _content(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def discover_cached_candle_files(root: str | Path = "research_data/coinbase/candles") -> List[str]:
    base = Path(root)
    if not base.exists():
        return []
    return sorted(str(path) for path in base.glob("product=*/timeframe=*/study_window=*.json") if path.is_file())


def _candle_identity(path: str | Path) -> Dict[str, str]:
    parts = Path(path).parts
    identity = {"ticker": "", "timeframe": "", "study_window": ""}
    for part in parts:
        if part.startswith("product="):
            identity["ticker"] = part.split("=", 1)[1].upper()
        elif part.startswith("timeframe="):
            identity["timeframe"] = part.split("=", 1)[1].upper()
        elif part.startswith("study_window="):
            identity["study_window"] = part.split("=", 1)[1].removesuffix(".json")
    if not identity["study_window"]:
        name = Path(path).name
        if name.startswith("study_window="):
            identity["study_window"] = name.split("=", 1)[1].removesuffix(".json")
    return identity


def _coverage_manifest_summary(paths: Iterable[str | Path]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        try:
            payload = _load_json(path)
        except Exception:
            continue
        for entry in payload.get("entries") or []:
            rows.append(
                {
                    "source_path": str(path),
                    "ticker": str(entry.get("ticker") or "").upper(),
                    "timeframe": str(entry.get("timeframe") or "").upper(),
                    "study_window": str(entry.get("study_window") or ""),
                    "candle_count": entry.get("candle_count"),
                    "gap_count": entry.get("gap_count"),
                    "coverage_class": entry.get("coverage_class"),
                }
            )
    return {
        "manifest_count": len(list(paths)),
        "entry_count": len(rows),
        "covered_tickers": sorted({row["ticker"] for row in rows if row["ticker"]}),
        "covered_pairs": sorted({f"{row['ticker']}|{row['timeframe']}|{row['study_window']}" for row in rows if row["ticker"]}),
        "rows": rows,
    }


def _cached_candle_summary(paths: Iterable[str | Path], *, as_of: str) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    quality_rows: List[Dict[str, Any]] = []
    for raw in paths:
        identity = _candle_identity(raw)
        rows.append({"path": str(raw), **identity})
        try:
            quality = build_phase_d6_dataset_quality_report(candles_path=raw, as_of=as_of)
        except Exception as exc:
            quality_rows.append(
                {
                    "path": str(raw),
                    **identity,
                    "status": "dataset_quality_error",
                    "quality_class": "invalid",
                    "error": str(exc),
                }
            )
            continue
        quality_rows.append(
            {
                "path": str(raw),
                **identity,
                "status": quality.get("status"),
                "quality_class": quality.get("quality_class"),
                "candle_count": quality.get("candle_count"),
                "gap_count": quality.get("gap_count"),
                "warnings": list(quality.get("warnings") or []),
            }
        )
    return {
        "cached_file_count": len(rows),
        "cached_tickers": sorted({row["ticker"] for row in rows if row["ticker"]}),
        "cached_timeframes": sorted({row["timeframe"] for row in rows if row["timeframe"]}),
        "cached_pairs": sorted({f"{row['ticker']}|{row['timeframe']}|{row['study_window']}" for row in rows if row["ticker"]}),
        "rows": rows,
        "dataset_quality_rows": quality_rows,
    }


def _order_event_summary(path: str | Path) -> Dict[str, Any]:
    event_types: Counter[str] = Counter()
    tickers: Counter[str] = Counter()
    live_tickers: Counter[str] = Counter()
    rows = 0
    p = Path(path)
    if not p.exists():
        return {"row_count": 0, "event_types": {}, "tickers": {}, "live_tickers": {}}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        rows += 1
        event_type = str(payload.get("event_type") or "")
        event_types[event_type] += 1
        order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
        ticker = str(payload.get("ticker") or payload.get("product_id") or order.get("ticker") or order.get("product_id") or "").upper()
        if ticker:
            tickers[ticker] += 1
        if ticker and (order.get("mode") == "live" or order.get("live_order_submitted") is True or "live" in event_type.lower()):
            live_tickers[ticker] += 1
    return {
        "row_count": rows,
        "event_types": dict(event_types.most_common()),
        "tickers": dict(tickers.most_common()),
        "live_tickers": dict(live_tickers.most_common()),
    }


def _fetch_plan_commands(*, as_of: str, tickers: List[str], required_timeframes: List[str]) -> Dict[str, Any]:
    missing_csv = ",".join(tickers)
    tf_csv = ",".join(required_timeframes)
    return {
        "dry_run_all_missing": (
            ".venv/bin/python tools/fetch_phase_d6_coinbase_candles.py "
            f"--as-of {as_of} --tickers {missing_csv} --timeframes {tf_csv} --years 3 "
            "--max-chunks 2 --dry-run --json"
        ),
        "bounded_fetch_requires_separate_ack": (
            ".venv/bin/python tools/fetch_phase_d6_coinbase_candles.py "
            f"--as-of {as_of} --tickers {missing_csv} --timeframes {tf_csv} --years 3 "
            "--max-chunks 2 --fetch --json"
        ),
        "operator_boundary": "Do not run the fetch command without a separate explicit data-fetch ACK.",
        "notes": [
            "max_chunks=2 is intentionally bounded for an initial ingest increment",
            "repeat or widen only under a separate data-fetch task",
            "fetching data does not authorize live trading or parameter changes",
        ],
    }


def _per_ticker_gap_rows(*, tickers: List[str], cached: Dict[str, Any], live_ticker: str) -> List[Dict[str, Any]]:
    cached_pairs = set(cached.get("cached_pairs") or [])
    cached_tickers = set(cached.get("cached_tickers") or [])
    quality_by_pair = {
        f"{row.get('ticker')}|{row.get('timeframe')}|{row.get('study_window')}": row
        for row in cached.get("dataset_quality_rows") or []
    }
    rows: List[Dict[str, Any]] = []
    for ticker in tickers:
        required_pairs = [f"{ticker}|{tf}|3y" for tf in D6_REQUIRED_TIMEFRAMES]
        present_required = [pair for pair in required_pairs if pair in cached_pairs]
        quality_rows = [quality_by_pair[pair] for pair in present_required if pair in quality_by_pair]
        has_any_quality = bool(quality_rows)
        has_backtest_input = f"{ticker}|1D|3y" in cached_pairs
        rows.append(
            {
                "ticker": ticker,
                "live_test_scope": ticker == live_ticker,
                "cached_any_timeframe": ticker in cached_tickers,
                "cached_required_pairs_present": present_required,
                "cached_required_pairs_missing": [pair for pair in required_pairs if pair not in cached_pairs],
                "dataset_quality_present": has_any_quality,
                "dataset_quality_classes": sorted({str(row.get("quality_class")) for row in quality_rows}),
                "cached_backtest_input_present": has_backtest_input,
                "all_required_coverage_ready": len(present_required) == len(required_pairs),
                "all_ticker_live_test_status": "blocked_missing_coverage_or_ack" if ticker != live_ticker else "btc_scope_only_ack_blocked",
                "btc_usdc_24h_status": "in_scope_warning_only" if ticker == live_ticker else "out_of_scope_for_first_24h_test",
            }
        )
    return rows


def _cached_baseline_summary(candle_paths: List[str]) -> Dict[str, Any]:
    if not candle_paths:
        return {
            "status": "not_run_no_cached_candles",
            "reason": "No local candle files were found.",
            "report": None,
        }
    one_day = [path for path in candle_paths if _candle_identity(path).get("timeframe") == "1D"]
    if not one_day:
        return {
            "status": "not_run_no_1d_cached_candles",
            "reason": "Cached-only baseline v1 uses local 1D candles.",
            "report": None,
        }
    try:
        report = build_phase_d6_cost_aware_baseline_bundle(
            candle_paths=one_day,
            cost_scenarios=["standard_fee_only"],
            split_mode="holdout",
            train_count=210,
            validation_count=70,
            test_count=70,
            step_count=70,
            max_splits=12,
            initial_quote="1000",
            require_quality_ready=False,
        )
    except Exception as exc:
        return {
            "status": "cached_baseline_error",
            "reason": str(exc),
            "report": None,
        }
    return {
        "status": "cached_only_baseline_executed_report_only",
        "reason": "Executed on local cached candle files only; no data fetch, optimization, ranking or parameter mutation.",
        "report": report,
    }


def _live_run_evidence_pack(live_ticker: str) -> Dict[str, Any]:
    return {
        "status": "live_run_evidence_schema_ready",
        "scope": {
            "duration": "24h_future_prompt_only",
            "product_scope": [live_ticker],
            "order_count_limit": 1,
            "no_multi_ticker_live_trading": True,
            "no_learning_to_execution": True,
            "no_parameter_changes": True,
        },
        "evidence_schema": [
            {"category": "preflight", "fields": ["timestamp", "state_hashes", "open_orders", "d3_status", "ack_matrix"]},
            {"category": "product_rules", "fields": ["product_id", "base_increment", "quote_increment", "min_market_funds"], "boundary": "Coinbase read-only ACK required"},
            {"category": "order_submit", "fields": ["client_order_id", "exchange_order_id", "side", "notional", "limit_price", "post_only"], "boundary": "live submit ACK required"},
            {"category": "lifecycle_snapshots", "fields": ["timestamp", "status", "filled_size", "remaining_size", "fees", "source"]},
            {"category": "fill_realism", "fields": ["maker_or_taker", "post_only_result", "fill_or_no_fill_duration", "spread_context"]},
            {"category": "fee_evidence", "fields": ["fee_amount", "fee_currency", "source", "lifecycle_fee_field_match"]},
            {"category": "d5_d6_rows", "fields": ["evidence_category", "parameter_category", "source_path", "human_review_required"]},
            {"category": "post_run", "fields": ["state_hashes", "open_orders", "open_d3_exit", "terminal_status", "apply_ack_status"]},
        ],
        "stop_triggers": [
            "unexpected_open_order_before_authorized_submit",
            "d3_exit_active_before_authorized_submit",
            "missing_next_boundary_ack",
            "order_rejected_or_terminal_without_apply_ack",
            "state_hash_drift_unexplained",
            "any_need_for_cancel_replace_reprice_without_ack",
        ],
    }


def _preflight_v2(*, live_ticker: str, gap_summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "future_24h_preflight_v2_ready_for_prompt_review",
        "safe_scope_for_next_prompt": {
            "product": live_ticker,
            "max_notional_usdc": "10",
            "order_count_limit": 1,
            "post_only_preferred": True,
            "multi_ticker_live_trading_allowed": False,
            "parameter_change_allowed": False,
            "learning_to_execution_allowed": False,
        },
        "required_preflight_inputs": [
            "local open order report",
            "function preservation audit",
            "D.3 controlled exit report",
            "state hashes",
            "Coinbase product rules only after read-only ACK",
            "account balance only after read-only ACK if needed",
            "explicit submit ACK before any order",
        ],
        "must_remain_separate": [
            "Coinbase read-only poll",
            "live submit",
            "cancel_replace_reprice",
            "lifecycle_apply",
            "local_repair_apply",
            "parameter_approval",
            "learning_to_execution",
            "system_package_mutation",
        ],
        "gap_disposition": {
            "btc_usdc_only_prompt_review": "possible_after_exact_ACKs_if_final_safety_refresh_passes",
            "all_ticker_live_test": "blocked",
            "all_ticker_blockers": gap_summary.get("all_ticker_blockers", []),
        },
        "future_ack_strings": {
            "ACK_COINBASE_READ_ONLY": "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "ACK_LIVE_SUBMIT": "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "ACK_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE": "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        },
    }


def build_phase_d6_24h_readiness_bundle(
    *,
    config_text: str,
    workflow_ticker_audit: Optional[Dict[str, Any]] = None,
    final_readiness_packet: Optional[Dict[str, Any]] = None,
    controlled_live_test_audit_plan: Optional[Dict[str, Any]] = None,
    coverage_manifest_paths: Iterable[str | Path] = (),
    candle_paths: Optional[Iterable[str | Path]] = None,
    order_events_path: str | Path = "logs/order_events.jsonl",
    state_hashes_before: Optional[Dict[str, str]] = None,
    state_hashes_after: Optional[Dict[str, str]] = None,
    as_of: str = DEFAULT_AS_OF,
    live_test_ticker: str = DEFAULT_LIVE_TEST_TICKER,
) -> Dict[str, Any]:
    configured = extract_default_allowed_tickers(config_text) or list(D6_DEFAULT_TICKERS)
    local_candles = sorted(str(path) for path in (candle_paths if candle_paths is not None else discover_cached_candle_files()))
    manifests = _coverage_manifest_summary(coverage_manifest_paths)
    cached = _cached_candle_summary(local_candles, as_of=as_of)
    event_summary = _order_event_summary(order_events_path)
    gap_rows = _per_ticker_gap_rows(tickers=configured, cached=cached, live_ticker=live_test_ticker)
    missing_any_required = [row["ticker"] for row in gap_rows if not row["all_required_coverage_ready"]]
    missing_backtest = [row["ticker"] for row in gap_rows if not row["cached_backtest_input_present"]]
    missing_live_evidence = sorted(set(configured) - set(event_summary.get("live_tickers") or {}))
    coverage_plan = build_phase_d6_data_coverage_report(
        as_of=as_of,
        tickers=configured,
        timeframes=D6_REQUIRED_TIMEFRAMES,
        years=[3],
    )
    gap_summary = {
        "configured_ticker_count": len(configured),
        "cached_candle_file_count": cached["cached_file_count"],
        "cached_tickers": cached["cached_tickers"],
        "tickers_missing_required_cached_coverage": missing_any_required,
        "tickers_missing_cached_backtest_input": missing_backtest,
        "tickers_missing_live_lifecycle_evidence": missing_live_evidence,
        "all_ticker_blockers": [
            "missing_cached_required_timeframes_for_all_tickers",
            "missing_dataset_quality_for_all_tickers",
            "missing_cached_backtest_inputs_for_all_tickers",
            "missing_live_lifecycle_evidence_for_non_btc_tickers",
            "missing_all_ticker_live_ACK",
        ],
        "btc_usdc_only_blockers": [
            "missing_Coinbase_read_only_ACK",
            "missing_live_submit_ACK",
            "missing_lifecycle_apply_ACK_for_future_terminal_apply",
        ],
    }
    return {
        "generated_at": now_iso(),
        "phase": D6_24H_READINESS_BUNDLE_PHASE,
        "status": "d6_24h_readiness_bundle_ready",
        "chosen_route": {
            "route": "F_combined_multiticker_gap_scaffold_evidence_preflight",
            "rationale": "Bundles multi-ticker gap mapping, cached-only baseline feasibility, 24h evidence schema and preflight v2 without fetching data or crossing live boundaries.",
        },
        "route_scores": [
            {"route": "A_multiticker_gap_fetch_plan", "value": 8, "risk": 1, "testability": 8, "size": 4, "selected": True},
            {"route": "B_cached_only_baseline", "value": 6, "risk": 2, "testability": 7, "size": 3, "selected": True},
            {"route": "C_scaffold_completion", "value": 8, "risk": 2, "testability": 8, "size": 6, "selected": True},
            {"route": "D_live_run_evidence_pack", "value": 9, "risk": 1, "testability": 8, "size": 5, "selected": True},
            {"route": "E_preflight_v2", "value": 9, "risk": 1, "testability": 7, "size": 5, "selected": True},
            {"route": "F_combined_bundle", "value": 10, "risk": 2, "testability": 8, "size": 8, "selected": True},
        ],
        "scope": {
            "report_only": True,
            "local_files_only": True,
            "coinbase_interaction": False,
            "openai_api_interaction": False,
            "bulk_data_fetch": False,
            "live_action": False,
            "trading_state_mutation": False,
            "config_parameter_mutation": False,
            "optimization": False,
            "learning_to_execution": False,
        },
        "current_readiness_inputs": {
            "workflow_ticker_audit_status": _content(workflow_ticker_audit).get("status"),
            "final_readiness_packet_status": _content(final_readiness_packet).get("final_status"),
            "controlled_live_test_audit_status": _content(controlled_live_test_audit_plan).get("status"),
        },
        "multiticker_gap_report": {
            "summary": gap_summary,
            "coverage_manifest_summary": manifests,
            "cached_candle_summary": cached,
            "order_event_summary": event_summary,
            "coverage_plan_entry_count": coverage_plan.get("entry_count"),
            "per_ticker_rows": gap_rows,
            "bounded_fetch_plan": _fetch_plan_commands(
                as_of=as_of,
                tickers=missing_any_required,
                required_timeframes=list(D6_REQUIRED_TIMEFRAMES),
            ),
        },
        "cached_only_backtest_status": _cached_baseline_summary(local_candles),
        "live_run_evidence_pack": _live_run_evidence_pack(live_test_ticker),
        "future_24h_preflight_v2": _preflight_v2(live_ticker=live_test_ticker, gap_summary=gap_summary),
        "backlearning_status_after_sprint": {
            "implemented_scaffold": True,
            "report_only_governance": True,
            "cached_only_baseline_executed_where_data_exists": bool(local_candles),
            "executed_on_all_configured_tickers": False,
            "parameter_search_performed": False,
            "parameter_review_approved": False,
            "parameter_values_changed_by_learning": False,
            "learning_to_execution_enabled": False,
        },
        "readiness_conclusion": {
            "btc_usdc_only_24h_ready_for_ack_review": True,
            "btc_usdc_only_caveat": "requires fresh final safety refresh and exact live boundary ACKs",
            "all_ticker_24h_live_test_ready": False,
            "all_ticker_reason": "The other configured tickers lack cached coverage, dataset-quality artifacts, cached backtest inputs and live lifecycle evidence in current local files.",
        },
        "state_hashes": {
            "before": dict(state_hashes_before or {}),
            "after": dict(state_hashes_after or state_hashes_before or {}),
            "match": dict(state_hashes_before or {}) == dict(state_hashes_after or state_hashes_before or {}),
        },
        "warnings": [
            "data_fetch_not_performed",
            "all_ticker_live_test_blocked",
            "btc_usdc_cached_dataset_has_stale_candle_warning_if_as_of_2026_06_01",
            "backlearning_remains_report_only",
        ],
        "blockers": gap_summary["btc_usdc_only_blockers"],
        **_safety_flags(),
    }


__all__ = [
    "D6_24H_READINESS_BUNDLE_PHASE",
    "build_phase_d6_24h_readiness_bundle",
    "discover_cached_candle_files",
]
