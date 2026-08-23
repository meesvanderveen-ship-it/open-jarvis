from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_WORKFLOW_TICKER_AUDIT_PHASE = "D6_workflow_ticker_coverage_audit_v1"
DEFAULT_FIRST_LIVE_TEST_TICKER = "BTC-USDC"


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


def extract_default_allowed_tickers(config_text: str) -> List[str]:
    match = re.search(r'"ALLOWED_TICKERS",\s*\((.*?)\)\s*,', config_text, flags=re.DOTALL)
    if not match:
        return []
    raw = "".join(re.findall(r'"([^"]+)"', match.group(1)))
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _coverage_from_manifest_paths(paths: Iterable[str | Path]) -> Dict[str, Any]:
    tickers: Counter[str] = Counter()
    rows: List[Dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in payload.get("entries") or []:
            ticker = str(entry.get("ticker") or "").upper()
            if ticker:
                tickers[ticker] += 1
            rows.append(
                {
                    "path": str(path),
                    "ticker": ticker,
                    "timeframe": entry.get("timeframe"),
                    "study_window": entry.get("study_window"),
                    "candle_count": entry.get("candle_count"),
                    "gap_count": entry.get("gap_count"),
                    "dataset_quality_status": entry.get("dataset_quality_status"),
                    "learning_to_execution_allowed": entry.get("learning_to_execution_allowed"),
                    "parameter_change_allowed": entry.get("parameter_change_allowed"),
                }
            )
    return {
        "covered_tickers": sorted(tickers),
        "coverage_entry_count": len(rows),
        "coverage_rows": rows,
    }


def _log_product_summary(log_path: str | Path) -> Dict[str, Any]:
    path = Path(log_path)
    event_types: Counter[str] = Counter()
    tickers: Counter[str] = Counter()
    live_tickers: Counter[str] = Counter()
    entry_tickers: Counter[str] = Counter()
    exit_tickers: Counter[str] = Counter()
    lifecycle_tickers: Counter[str] = Counter()
    rows = 0
    if not path.exists():
        return {
            "row_count": 0,
            "event_types": {},
            "tickers": {},
            "live_tickers": {},
            "entry_tickers": {},
            "exit_tickers": {},
            "lifecycle_tickers": {},
        }
    for line in path.read_text(encoding="utf-8").splitlines():
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
        ticker = str(
            payload.get("ticker") or payload.get("product_id") or order.get("ticker") or order.get("product_id") or ""
        ).upper()
        if not ticker:
            continue
        tickers[ticker] += 1
        event_l = event_type.lower()
        if order.get("mode") == "live" or order.get("live_order_submitted") is True or "live" in event_l:
            live_tickers[ticker] += 1
        if "entry" in event_l or str(order.get("side") or "").upper() == "BUY":
            entry_tickers[ticker] += 1
        if "exit" in event_l or str(order.get("side") or "").upper() == "SELL":
            exit_tickers[ticker] += 1
        if any(token in event_l for token in ("lifecycle", "filled", "cancel", "rejected", "reconcile")):
            lifecycle_tickers[ticker] += 1
    return {
        "row_count": rows,
        "event_types": dict(event_types.most_common()),
        "tickers": dict(tickers.most_common()),
        "live_tickers": dict(live_tickers.most_common()),
        "entry_tickers": dict(entry_tickers.most_common()),
        "exit_tickers": dict(exit_tickers.most_common()),
        "lifecycle_tickers": dict(lifecycle_tickers.most_common()),
    }


def _workflow_overview() -> List[Dict[str, Any]]:
    return [
        {
            "stage": "A_universe_ticker_selection",
            "status": "configured_multi_ticker_live_test_scope_btc_usdc_only",
            "evidence": ["bot/config.py:ALLOWED_TICKERS", "phase_c_allowed_tickers gate usage"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Default universe contains multiple products, but first controlled live-test scope remains BTC-USDC only.",
        },
        {
            "stage": "B_data_layer",
            "status": "partial_multi_ticker_coverage",
            "evidence": ["reports/d6/coverage", "logs/order_events.jsonl"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Cached D.6 candle coverage is currently BTC-USDC-only in local artifacts.",
        },
        {
            "stage": "C_analysis_agents_decision_layer",
            "status": "implemented_but_api_calls_not_used_in_this_audit",
            "evidence": ["bot/config.py OpenAI model settings", "StrategyEngine-related tests", "function preservation audit"],
            "btc_usdc_live_test_blocker": False,
            "notes": "LLM decision layers exist but this audit made no OpenAI API call and did not alter prompts or parameters.",
        },
        {
            "stage": "D_gatekeeper_risk_layer",
            "status": "implemented_and_observe_only_locally",
            "evidence": ["function preservation audit", "D.3 controlled exit report", "reservation governance"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Live submit, lifecycle apply, repair and Coinbase inspection remain ACK-gated.",
        },
        {
            "stage": "E_entry_order_workflow",
            "status": "implemented_and_tested_with_btc_usdc_evidence",
            "evidence": ["C.4.3 controlled entry tools/tests", "order_events BTC-USDC rows"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Entry workflow is not proven for the other configured tickers in current local live evidence.",
        },
        {
            "stage": "F_monitoring_workflow",
            "status": "implemented_ack_gated_for_exchange_reads",
            "evidence": ["local open order tools", "D.3 lifecycle manager tooling"],
            "btc_usdc_live_test_blocker": True,
            "notes": "Bounded Coinbase read-only monitoring requires a future exact ACK.",
        },
        {
            "stage": "G_position_workflow",
            "status": "implemented_btc_usdc_closed_zero_now",
            "evidence": ["state/positions.json", "D.3 reservation governance"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Current BTC-USDC position is closed/zero; stale denormalized reservation is documented as a warning.",
        },
        {
            "stage": "H_exit_workflow",
            "status": "implemented_and_live_lifecycle_proven_for_btc_usdc",
            "evidence": ["D.2/D.3/D.4 tools", "TP1 and TP_CLOSE local filled lifecycle evidence"],
            "btc_usdc_live_test_blocker": False,
            "notes": "No TP2/trailing/reprice route is authorized for the next controlled live test.",
        },
        {
            "stage": "I_logging_evidence_workflow",
            "status": "implemented_report_only_outputs_validated",
            "evidence": ["logs/order_events.jsonl", "D.6 governance/readiness/final packet reports"],
            "btc_usdc_live_test_blocker": False,
            "notes": "Evidence capture is sufficient for BTC-USDC workflow review, but multi-ticker live evidence is missing.",
        },
        {
            "stage": "J_learning_backlearning_workflow",
            "status": "scaffolded_governance_tested_report_only",
            "evidence": ["D.5 adapter", "D.6 parameter inventory/review/human export"],
            "btc_usdc_live_test_blocker": False,
            "notes": "No parameter search, approval, mutation or learning-to-execution is enabled.",
        },
        {
            "stage": "K_future_live_test_workflow",
            "status": "planned_blocked_until_exact_ack",
            "evidence": ["final readiness packet", "controlled live-test audit plan", "future prompt skeleton"],
            "btc_usdc_live_test_blocker": True,
            "notes": "The next boundary is an operator ACK prompt, not autonomous execution.",
        },
    ]


def _ticker_row(
    ticker: str,
    *,
    coverage_tickers: set[str],
    log_summary: Dict[str, Any],
    live_test_ticker: str,
) -> Dict[str, Any]:
    has_coverage = ticker in coverage_tickers
    has_rows = ticker in set(log_summary.get("tickers") or {})
    has_live = ticker in set(log_summary.get("live_tickers") or {})
    has_entry = ticker in set(log_summary.get("entry_tickers") or {})
    has_exit = ticker in set(log_summary.get("exit_tickers") or {})
    has_lifecycle = ticker in set(log_summary.get("lifecycle_tickers") or {}) or has_live
    if has_live and ticker == live_test_ticker:
        classification = "live_workflow_proven"
        blocker = "hard_blocker_only_missing_exact_live_acks"
    elif has_coverage:
        classification = "research_covered"
        blocker = "out_of_scope_for_first_live_test_non_blocking_warning"
    else:
        classification = "configured_only_missing_coverage"
        blocker = "out_of_scope_for_first_live_test_non_blocking_warning"
    return {
        "ticker": ticker,
        "configured_allowed": True,
        "live_test_scope": ticker == live_test_ticker,
        "d6_coverage_inventory_present": has_coverage,
        "candle_data_present": has_coverage,
        "dataset_quality_present": False,
        "regime_evidence_review_present": has_coverage and ticker == live_test_ticker,
        "parameter_inventory_applicable": True,
        "d5_d6_evidence_rows_present": has_rows,
        "live_lifecycle_evidence_present": has_live,
        "entry_workflow_tested": has_entry,
        "exit_workflow_tested": has_exit,
        "order_lifecycle_tested": has_lifecycle,
        "readiness_classification": classification,
        "blocker_status_for_btc_usdc_only_live_test": blocker,
    }


def _backlearning_audit(coverage: Dict[str, Any], allowed_tickers: List[str], live_tickers: List[str]) -> Dict[str, Any]:
    covered = set(coverage.get("covered_tickers") or [])
    return {
        "is_backlearning_implemented": True,
        "implemented_scaffold": True,
        "report_only_governance": True,
        "executed_on_cached_data": bool(covered),
        "executed_on_all_configured_tickers": bool(allowed_tickers) and set(allowed_tickers).issubset(covered),
        "parameter_search_performed": False,
        "parameter_review_approved": False,
        "parameter_values_changed_by_learning": False,
        "learning_to_execution_enabled": False,
        "real_live_lifecycle_evidence_products": sorted(live_tickers),
        "fixture_or_report_only_evidence": [
            "parameter_inventory",
            "regime_segmentation_scaffold",
            "fill_realism_assumptions",
            "human_review_export",
            "governance_evidence_bundle",
        ],
        "later_full_multi_crypto_work": [
            "fetch_or_import candle coverage for every configured ticker",
            "produce dataset quality artifacts per ticker",
            "produce regime and fill-realism review artifacts per ticker",
            "keep human review separate from execution",
            "do not enable parameter mutation without exact future ACK",
        ],
    }


def _blocker_classification() -> Dict[str, Any]:
    return {
        "hard_blockers_before_tiny_btc_usdc_live_test": [
            "Gate_5_exact_live_test_ACK_missing",
            "Coinbase_read_only_preflight_ACK_missing",
            "live_submit_ACK_missing",
            "lifecycle_apply_ACK_missing_for_any_future_terminal_apply",
        ],
        "non_blocking_warnings_for_btc_usdc_only_scope": [
            "stale_denormalized_reserved_base_open_exit_orders",
            "TP_CLOSE_fee_field_gap",
            "bwrap_missing_on_PATH",
            "multi_crypto_D6_coverage_incomplete",
            "multi_crypto_backlearning_incomplete",
            "only_BTC_USDC_has_live_lifecycle_evidence",
        ],
        "desired_non_blockers": [
            "parameter_review_approved_false",
            "learning_to_execution_disabled",
            "parameter_change_allowed_false",
            "no_optimization_performed",
        ],
        "scope_rule": "First controlled live test must remain BTC-USDC-only unless separate coverage and ACKs are added.",
    }


def build_phase_d6_workflow_ticker_audit(
    *,
    config_text: str,
    order_events_path: str | Path,
    coverage_manifest_paths: Iterable[str | Path],
    final_readiness_packet: Optional[Dict[str, Any]] = None,
    controlled_live_test_audit_plan: Optional[Dict[str, Any]] = None,
    state_hashes_before: Optional[Dict[str, str]] = None,
    state_hashes_after: Optional[Dict[str, str]] = None,
    live_test_ticker: str = DEFAULT_FIRST_LIVE_TEST_TICKER,
) -> Dict[str, Any]:
    allowed_tickers = extract_default_allowed_tickers(config_text)
    coverage = _coverage_from_manifest_paths(coverage_manifest_paths)
    log_summary = _log_product_summary(order_events_path)
    covered = set(coverage.get("covered_tickers") or [])
    live_tickers = sorted(log_summary.get("live_tickers") or {})
    table = [
        _ticker_row(ticker, coverage_tickers=covered, log_summary=log_summary, live_test_ticker=live_test_ticker)
        for ticker in allowed_tickers
    ]
    proven = [row["ticker"] for row in table if row["readiness_classification"] == "live_workflow_proven"]
    research = [row["ticker"] for row in table if row["readiness_classification"] == "research_covered"]
    configured_only = [row["ticker"] for row in table if row["readiness_classification"] == "configured_only_missing_coverage"]
    final_packet = _content(final_readiness_packet)
    controlled_plan = _content(controlled_live_test_audit_plan)
    hashes_before = dict(state_hashes_before or {})
    hashes_after = dict(state_hashes_after or state_hashes_before or {})
    workflow = _workflow_overview()
    hard_blockers = _blocker_classification()["hard_blockers_before_tiny_btc_usdc_live_test"]
    return {
        "generated_at": now_iso(),
        "phase": D6_WORKFLOW_TICKER_AUDIT_PHASE,
        "status": "workflow_ticker_coverage_audit_ready",
        "scope": {
            "report_only": True,
            "local_files_only": True,
            "coinbase_interaction": False,
            "openai_api_interaction": False,
            "live_action": False,
            "trading_state_mutation": False,
            "config_parameter_mutation": False,
            "system_mutation": False,
        },
        "workflow_correctness_conclusion": {
            "btc_usdc_end_to_end_workflow_coherent": live_test_ticker in proven,
            "multi_ticker_live_workflow_coherent": False,
            "reason": "Local artifacts prove BTC-USDC lifecycle and evidence flow, while other configured tickers lack local D.6 coverage and live lifecycle evidence.",
            "next_boundary": "future_exact_ACK_prompt_before_any_Coinbase_or_live_action",
        },
        "configured_ticker_universe": {
            "source": "bot/config.py default ALLOWED_TICKERS",
            "count": len(allowed_tickers),
            "tickers": allowed_tickers,
            "first_live_test_scope": [live_test_ticker],
        },
        "workflow_overview": workflow,
        "workflow_stage_status_counts": dict(Counter(row["status"] for row in workflow)),
        "ticker_coverage_table": table,
        "ticker_classification_summary": {
            "live_workflow_proven": proven,
            "research_covered": research,
            "configured_only_missing_coverage": configured_only,
            "missing_coverage": sorted(set(allowed_tickers) - covered),
        },
        "coverage_evidence": {
            "d6_coverage": coverage,
            "order_event_log_summary": log_summary,
        },
        "backlearning_audit": _backlearning_audit(coverage, allowed_tickers, live_tickers),
        "pre_live_hard_blocker_check": _blocker_classification(),
        "readiness_inputs": {
            "final_readiness_packet_status": final_packet.get("final_status"),
            "controlled_live_test_plan_status": controlled_plan.get("status"),
            "controlled_live_test_chosen_future_route": (controlled_plan.get("chosen_future_route") or {}).get("route"),
        },
        "state_hashes": {
            "before": hashes_before,
            "after": hashes_after,
            "match": hashes_before == hashes_after,
        },
        "blockers": hard_blockers,
        "warnings": _blocker_classification()["non_blocking_warnings_for_btc_usdc_only_scope"],
        "exact_acks_required_before_live_test": {
            "ACK_COINBASE_READ_ONLY": "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "ACK_LIVE_SUBMIT": "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "ACK_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE": "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        },
        **_safety_flags(),
    }


__all__ = [
    "D6_WORKFLOW_TICKER_AUDIT_PHASE",
    "build_phase_d6_workflow_ticker_audit",
    "extract_default_allowed_tickers",
]
