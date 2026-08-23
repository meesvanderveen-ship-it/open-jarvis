from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_data_coverage import D6_DEFAULT_TICKERS, D6_REQUIRED_TIMEFRAMES, build_phase_d6_data_coverage_report
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_workflow_ticker_audit import extract_default_allowed_tickers


D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE = "D6_multi_ticker_backlearning_readiness_v1"
DEFAULT_AS_OF = "2026-06-01T00:00:00Z"
DEFAULT_LIVE_TEST_TICKER = "BTC-USDC"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"


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
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
    }


def _allowed_tickers(config_text: str) -> List[str]:
    return extract_default_allowed_tickers(config_text) or list(D6_DEFAULT_TICKERS)


def discover_cached_candle_files(root: str | Path = "research_data/coinbase/candles") -> List[str]:
    base = Path(root)
    if not base.exists():
        return []
    return sorted(str(path) for path in base.glob("product=*/timeframe=*/study_window=*.json") if path.is_file())


def _identity(path: str | Path) -> Dict[str, str]:
    result = {"ticker": "", "timeframe": "", "study_window": ""}
    p = Path(path)
    for part in p.parts:
        if part.startswith("product="):
            result["ticker"] = part.split("=", 1)[1].upper()
        elif part.startswith("timeframe="):
            result["timeframe"] = part.split("=", 1)[1].upper()
        elif part.startswith("study_window="):
            result["study_window"] = part.split("=", 1)[1].removesuffix(".json")
    return result


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _quality_for(path: str | Path, *, as_of: str) -> Dict[str, Any]:
    try:
        report = build_phase_d6_dataset_quality_report(candles_path=path, as_of=as_of)
    except Exception as exc:
        return {"status": "dataset_quality_error", "quality_class": "invalid", "error": str(exc)}
    return {
        "status": report.get("status"),
        "quality_class": report.get("quality_class"),
        "candle_count": report.get("candle_count"),
        "gap_count": report.get("gap_count"),
        "warnings": list(report.get("warnings") or []),
        "fatal_errors": list(report.get("fatal_errors") or []),
    }


def _cached_index(paths: Iterable[str | Path], *, as_of: str) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for raw in paths:
        ident = _identity(raw)
        if not ident["ticker"] or not ident["timeframe"]:
            continue
        key = f"{ident['ticker']}|{ident['timeframe']}"
        quality = _quality_for(raw, as_of=as_of)
        index[key] = {
            "ticker": ident["ticker"],
            "timeframe": ident["timeframe"],
            "study_window": ident["study_window"],
            "path": str(raw),
            "cached_data_present": True,
            "dataset_quality": quality,
            "candle_count": quality.get("candle_count"),
            "freshness_status": "stale" if "stale_last_candle" in quality.get("warnings", []) else "freshness_ok_or_not_checked",
        }
    return index


def _event_summary(order_events_path: str | Path) -> Dict[str, Any]:
    p = Path(order_events_path)
    rows = 0
    tickers: Counter[str] = Counter()
    live_tickers: Counter[str] = Counter()
    exit_tickers: Counter[str] = Counter()
    entry_tickers: Counter[str] = Counter()
    if not p.exists():
        return {"row_count": 0, "tickers": {}, "live_tickers": {}, "entry_tickers": {}, "exit_tickers": {}}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        rows += 1
        order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
        event_type = str(payload.get("event_type") or "")
        ticker = str(payload.get("ticker") or payload.get("product_id") or order.get("ticker") or order.get("product_id") or "").upper()
        if not ticker:
            continue
        tickers[ticker] += 1
        event_l = event_type.lower()
        side = str(order.get("side") or "").upper()
        if order.get("mode") == "live" or order.get("live_order_submitted") is True or "live" in event_l:
            live_tickers[ticker] += 1
        if "entry" in event_l or side == "BUY":
            entry_tickers[ticker] += 1
        if "exit" in event_l or side == "SELL":
            exit_tickers[ticker] += 1
    return {
        "row_count": rows,
        "tickers": dict(tickers.most_common()),
        "live_tickers": dict(live_tickers.most_common()),
        "entry_tickers": dict(entry_tickers.most_common()),
        "exit_tickers": dict(exit_tickers.most_common()),
    }


def _fetch_commands(*, ticker: str, timeframe: str, as_of: str) -> Dict[str, str]:
    base = (
        ".venv/bin/python tools/fetch_phase_d6_coinbase_candles.py "
        f"--as-of {as_of} --tickers {ticker} --timeframes {timeframe} --years 3 --max-chunks 2"
    )
    return {
        "dry_run": f"{base} --dry-run --json",
        "fetch_after_ack": f"{base} --fetch --json",
        "required_ack": DATA_FETCH_ACK,
    }


def _base_context(
    *,
    config_text: str,
    candle_paths: Optional[Iterable[str | Path]],
    order_events_path: str | Path,
    as_of: str,
) -> Dict[str, Any]:
    tickers = _allowed_tickers(config_text)
    paths = sorted(str(path) for path in (candle_paths if candle_paths is not None else discover_cached_candle_files()))
    return {
        "tickers": tickers,
        "candle_paths": paths,
        "cached_index": _cached_index(paths, as_of=as_of),
        "event_summary": _event_summary(order_events_path),
        "as_of": as_of,
    }


def build_multi_ticker_dataset_coverage_plan(
    *,
    config_text: str,
    candle_paths: Optional[Iterable[str | Path]] = None,
    order_events_path: str | Path = "logs/order_events.jsonl",
    as_of: str = DEFAULT_AS_OF,
) -> Dict[str, Any]:
    ctx = _base_context(config_text=config_text, candle_paths=candle_paths, order_events_path=order_events_path, as_of=as_of)
    rows: List[Dict[str, Any]] = []
    for ticker in ctx["tickers"]:
        for timeframe in D6_REQUIRED_TIMEFRAMES:
            cached = ctx["cached_index"].get(f"{ticker}|{timeframe}")
            missing = cached is None
            rows.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "cached_data_present": not missing,
                    "cached_candles_path": "" if missing else cached["path"],
                    "candle_count": None if missing else cached.get("candle_count"),
                    "freshness_status": "missing" if missing else cached.get("freshness_status"),
                    "dataset_quality_status": "missing" if missing else (cached.get("dataset_quality") or {}).get("status"),
                    "dataset_quality_class": "missing" if missing else (cached.get("dataset_quality") or {}).get("quality_class"),
                    "missing_data_blocker": missing,
                    "warning": "missing_cached_required_timeframe" if missing else ",".join((cached.get("dataset_quality") or {}).get("warnings") or []),
                    "future_fetch_command": _fetch_commands(ticker=ticker, timeframe=timeframe, as_of=as_of),
                }
            )
    coverage_plan = build_phase_d6_data_coverage_report(
        as_of=as_of,
        tickers=ctx["tickers"],
        timeframes=D6_REQUIRED_TIMEFRAMES,
        years=[3],
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "multi_ticker_dataset_coverage_plan_v1",
        "status": "multi_ticker_dataset_coverage_plan_ready",
        "as_of": as_of,
        "configured_ticker_count": len(ctx["tickers"]),
        "required_timeframes": list(D6_REQUIRED_TIMEFRAMES),
        "row_count": len(rows),
        "cached_file_count": len(ctx["candle_paths"]),
        "cached_tickers": sorted({row["ticker"] for row in rows if row["cached_data_present"]}),
        "missing_row_count": sum(1 for row in rows if row["missing_data_blocker"]),
        "coverage_inventory_entry_count": coverage_plan.get("entry_count"),
        "rows": rows,
        "data_fetch_boundary": {
            "fetch_not_performed": True,
            "required_ack": DATA_FETCH_ACK,
            "max_chunks_per_command": 2,
            "writes_outside_state": True,
        },
        **_safety_flags(),
    }


def build_multi_ticker_backtest_readiness_matrix(
    *,
    config_text: str,
    candle_paths: Optional[Iterable[str | Path]] = None,
    order_events_path: str | Path = "logs/order_events.jsonl",
    as_of: str = DEFAULT_AS_OF,
) -> Dict[str, Any]:
    coverage = build_multi_ticker_dataset_coverage_plan(
        config_text=config_text,
        candle_paths=candle_paths,
        order_events_path=order_events_path,
        as_of=as_of,
    )
    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    for row in coverage["rows"]:
        by_ticker.setdefault(row["ticker"], []).append(row)
    events = _event_summary(order_events_path)
    live = set(events.get("live_tickers") or {})
    rows: List[Dict[str, Any]] = []
    for ticker in coverage["rows"][0:0]:
        _ = ticker
    for ticker, tf_rows in by_ticker.items():
        missing_tfs = [r["timeframe"] for r in tf_rows if not r["cached_data_present"]]
        quality_missing = [r["timeframe"] for r in tf_rows if r["dataset_quality_status"] == "missing"]
        has_1d = any(r["timeframe"] == "1D" and r["cached_data_present"] for r in tf_rows)
        live_evidence = ticker in live
        classes = []
        if has_1d:
            classes.append("ready_for_cached_baseline")
        if missing_tfs:
            classes.append("missing_required_timeframes")
        if quality_missing:
            classes.append("missing_dataset_quality")
        if not has_1d:
            classes.append("missing_backtest_input")
        if not live_evidence:
            classes.append("missing_live_lifecycle_evidence")
        if missing_tfs or quality_missing or not has_1d or not live_evidence:
            classes.append("blocked_for_all_ticker_live_test")
        rows.append(
            {
                "ticker": ticker,
                "required_timeframes_present": [r["timeframe"] for r in tf_rows if r["cached_data_present"]],
                "required_timeframes_missing": missing_tfs,
                "dataset_quality_present": not quality_missing,
                "dataset_quality_missing_timeframes": quality_missing,
                "baseline_backtest_possible": has_1d,
                "cost_scenario_support_present": True,
                "fill_realism_evidence_present": live_evidence,
                "live_lifecycle_evidence_present": live_evidence,
                "readiness_class": classes,
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "multi_ticker_backtest_readiness_matrix_v1",
        "status": "multi_ticker_backtest_readiness_matrix_ready",
        "rows": rows,
        "summary": {
            "ticker_count": len(rows),
            "baseline_possible_tickers": [r["ticker"] for r in rows if r["baseline_backtest_possible"]],
            "all_ticker_live_test_blocked": True,
            "blocked_tickers": [r["ticker"] for r in rows if "blocked_for_all_ticker_live_test" in r["readiness_class"]],
        },
        **_safety_flags(),
    }


def build_backlearning_trial_accounting_guardrails(
    *,
    readiness_matrix: Dict[str, Any],
    min_candles_per_timeframe: int = 350,
    max_trials_per_100_candles: int = 1,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for row in readiness_matrix.get("rows") or []:
        missing = list(row.get("required_timeframes_missing") or [])
        blocked_reasons: List[str] = []
        if missing:
            blocked_reasons.append("incomplete_multi_timeframe_data")
        if not row.get("dataset_quality_present"):
            blocked_reasons.append("missing_dataset_quality")
        if not row.get("baseline_backtest_possible"):
            blocked_reasons.append("missing_backtest_input")
        if not row.get("fill_realism_evidence_present"):
            blocked_reasons.append("missing_cost_or_fill_realism_assumptions")
        blocked_reasons.extend(["missing_out_of_sample_windows", "missing_human_review"])
        rows.append(
            {
                "ticker": row["ticker"],
                "trial_unit": "ticker_strategy_timeframe_cost_scenario",
                "trial_count_recorded": 0,
                "max_trials_per_100_candles": max_trials_per_100_candles,
                "min_candles_per_timeframe": min_candles_per_timeframe,
                "oos_holdout_label_required": True,
                "data_too_thin_warning": bool(missing),
                "parameter_review_blocked": True,
                "block_reasons": sorted(set(blocked_reasons)),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "backlearning_trial_accounting_guardrails_v1",
        "status": "backlearning_trial_accounting_guardrails_ready",
        "rows": rows,
        "summary": {
            "ticker_count": len(rows),
            "parameter_review_blocked_ticker_count": sum(1 for row in rows if row["parameter_review_blocked"]),
            "optimization_performed": False,
            "ranking_performed": False,
        },
        **_safety_flags(),
    }


def build_backlearning_parameter_candidate_scaffold(
    *,
    readiness_matrix: Dict[str, Any],
    guardrails: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    guard_by_ticker = {row["ticker"]: row for row in (guardrails or {}).get("rows") or []}
    rows: List[Dict[str, Any]] = []
    for row in readiness_matrix.get("rows") or []:
        ticker = row["ticker"]
        guard = guard_by_ticker.get(ticker, {})
        rows.append(
            {
                "ticker": ticker,
                "parameter_families": [
                    "entry_filters",
                    "exit_lifecycle",
                    "position_sizing",
                    "cost_model",
                    "fill_realism",
                    "risk_limits",
                ],
                "evidence_required_before_human_review": [
                    "complete_1h_4h_1d_dataset_quality",
                    "cached_baseline_reports",
                    "walk_forward_oos_labels",
                    "cost_and_fill_realism_assumptions",
                    "trial_accounting_report",
                    "human_review_ack",
                ],
                "missing_datasets": list(row.get("required_timeframes_missing") or []),
                "missing_backtest_windows": ["oos_holdout"] if row.get("required_timeframes_missing") else ["oos_holdout"],
                "guardrails_required": list(guard.get("block_reasons") or ["missing_human_review"]),
                "human_ack_required_for_real_parameter_review": True,
                "parameter_review_approved": False,
                "parameter_values_changed": False,
                "learning_to_execution_enabled": False,
                "optimization_performed": False,
                "ranking_performed": False,
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "backlearning_parameter_candidate_scaffold_v1",
        "status": "backlearning_parameter_candidate_scaffold_ready",
        "rows": rows,
        "trial_accounting_guardrails": guardrails or {},
        "summary": {
            "ticker_count": len(rows),
            "all_parameter_reviews_blocked": True,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_changed": False,
            "learning_to_execution_enabled": False,
        },
        **_safety_flags(),
    }


def build_multi_ticker_workflow_equivalence_report(
    *,
    readiness_matrix: Dict[str, Any],
    order_events_path: str | Path = "logs/order_events.jsonl",
    reference_ticker: str = DEFAULT_LIVE_TEST_TICKER,
) -> Dict[str, Any]:
    events = _event_summary(order_events_path)
    live = set(events.get("live_tickers") or {})
    entry = set(events.get("entry_tickers") or {})
    exit_ = set(events.get("exit_tickers") or {})
    rows: List[Dict[str, Any]] = []
    for row in readiness_matrix.get("rows") or []:
        ticker = row["ticker"]
        is_reference = ticker == reference_ticker
        blockers: List[str] = []
        if row.get("required_timeframes_missing"):
            blockers.append("missing_candle_coverage_1h_4h_1d")
        if not row.get("dataset_quality_present"):
            blockers.append("missing_dataset_quality")
        if not row.get("baseline_backtest_possible"):
            blockers.append("missing_baseline_backtest_input")
        if ticker not in live:
            blockers.append("missing_live_lifecycle_evidence")
        rows.append(
            {
                "ticker": ticker,
                "reference_ticker": reference_ticker,
                "configured_in_universe": True,
                "product_rules_availability_source_local": False,
                "candle_coverage_1h_4h_1d": not row.get("required_timeframes_missing"),
                "dataset_quality": row.get("dataset_quality_present"),
                "baseline_backtest_readiness": row.get("baseline_backtest_possible"),
                "fill_realism_evidence": row.get("fill_realism_evidence_present"),
                "lifecycle_evidence": ticker in live,
                "d2_d3_workflow_evidence": ticker in exit_,
                "entry_workflow_evidence": ticker in entry,
                "open_order_safety_compatibility": True,
                "readiness_for_future_controlled_live_pilot": "btc_scope_ack_blocked" if is_reference else "blocked_until_equivalent_evidence",
                "blockers_before_ticker_can_join_24h_live_test": blockers,
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "multi_ticker_workflow_equivalence_report_v1",
        "status": "multi_ticker_workflow_equivalence_report_ready",
        "reference_ticker": reference_ticker,
        "rows": rows,
        "summary": {
            "reference_ticker": reference_ticker,
            "equivalent_to_reference_tickers": [row["ticker"] for row in rows if not row["blockers_before_ticker_can_join_24h_live_test"]],
            "non_equivalent_tickers": [row["ticker"] for row in rows if row["blockers_before_ticker_can_join_24h_live_test"]],
        },
        **_safety_flags(),
    }


def build_future_multi_ticker_fetch_plan_v2(
    *,
    dataset_coverage_plan: Dict[str, Any],
    as_of: str = DEFAULT_AS_OF,
) -> Dict[str, Any]:
    missing_rows = [row for row in dataset_coverage_plan.get("rows") or [] if row.get("missing_data_blocker")]
    tickers = sorted({row["ticker"] for row in missing_rows})
    timeframes = list(D6_REQUIRED_TIMEFRAMES)
    command = (
        ".venv/bin/python tools/fetch_phase_d6_coinbase_candles.py "
        f"--as-of {as_of} --tickers {','.join(tickers)} --timeframes {','.join(timeframes)} --years 3 --max-chunks 2"
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "future_multi_ticker_fetch_plan_v2",
        "status": "future_multi_ticker_fetch_plan_ready_ack_required",
        "missing_row_count": len(missing_rows),
        "missing_tickers": tickers,
        "required_timeframes": timeframes,
        "dry_run_command": f"{command} --dry-run --json",
        "fetch_command_after_ack": f"{command} --fetch --json",
        "required_ack": DATA_FETCH_ACK,
        "constraints": {
            "max_chunks_per_run": 2,
            "output_paths_outside_state": True,
            "env_mutation": False,
            "state_writes": False,
            "live_trading": False,
        },
        **_safety_flags(),
    }


def build_24h_live_test_readiness_v3(
    *,
    readiness_matrix: Dict[str, Any],
    backlearning_scaffold: Dict[str, Any],
    workflow_equivalence: Dict[str, Any],
    live_test_ticker: str = DEFAULT_LIVE_TEST_TICKER,
) -> Dict[str, Any]:
    matrix_rows = {row["ticker"]: row for row in readiness_matrix.get("rows") or []}
    btc = matrix_rows.get(live_test_ticker, {})
    all_ticker_blocked = bool(readiness_matrix.get("summary", {}).get("blocked_tickers"))
    return {
        "generated_at": now_iso(),
        "phase": D6_MULTI_TICKER_BACKLEARNING_READINESS_PHASE,
        "report_name": "24h_live_test_readiness_v3",
        "status": "24h_live_test_readiness_v3_ready",
        "routes": {
            "btc_usdc_only_24h": {
                "status": "warn_ack_required",
                "missing_evidence": [
                    "fresh_coinbase_read_only_preflight_after_ack",
                    "fresh_product_rules_after_ack",
                    "terminal_lifecycle_apply_ack_for_future_terminal_apply",
                ],
                "needed_acks": [
                    "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
                    "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
                    "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
                ],
                "stop_conditions": [
                    "unexpected_open_order",
                    "active_d3_exit",
                    "missing_next_boundary_ack",
                    "unclear_product_rules_or_balance",
                    "state_hash_drift",
                ],
                "telemetry_during_24h": [
                    "order_lifecycle_snapshots",
                    "fill_or_no_fill_duration",
                    "fee_evidence",
                    "post_only_maker_outcome",
                    "d5_d6_evidence_rows",
                    "final_state_hashes",
                ],
                "learning_to_execution_enabled": False,
                "parameter_values_changed": False,
                "coverage_warnings": btc.get("required_timeframes_missing", []),
            },
            "all_ticker_24h": {
                "status": "blocked",
                "missing_evidence": readiness_matrix.get("summary", {}).get("blocked_tickers", []),
                "needed_acks": [DATA_FETCH_ACK, "future_all_ticker_live_scope_ack"],
                "stop_conditions": ["do_not_trade_all_tickers_until_coverage_and_backlearning_readiness_complete"],
                "telemetry_during_24h": [],
                "learning_to_execution_enabled": False,
                "parameter_values_changed": False,
                "blocked_reason": "coverage_backtest_workflow_equivalence_incomplete" if all_ticker_blocked else "",
            },
        },
        "backlearning_status": {
            "parameter_review_approved": False,
            "parameter_values_changed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "learning_to_execution_enabled": False,
            "all_reviews_blocked": backlearning_scaffold.get("summary", {}).get("all_parameter_reviews_blocked", True),
        },
        "workflow_equivalence_summary": workflow_equivalence.get("summary", {}),
        **_safety_flags(),
    }


__all__ = [
    "DATA_FETCH_ACK",
    "build_24h_live_test_readiness_v3",
    "build_backlearning_parameter_candidate_scaffold",
    "build_backlearning_trial_accounting_guardrails",
    "build_future_multi_ticker_fetch_plan_v2",
    "build_multi_ticker_backtest_readiness_matrix",
    "build_multi_ticker_dataset_coverage_plan",
    "build_multi_ticker_workflow_equivalence_report",
    "discover_cached_candle_files",
]
