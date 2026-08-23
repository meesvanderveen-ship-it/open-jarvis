from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_REMAINING_WORK_PLANNER_PHASE = "D6_remaining_workflow_planner_v1"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"
BTC_READ_ACK = "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST"
BTC_SUBMIT_ACK = "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC"
BTC_APPLY_ACK = "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER"


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


def _content(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def _rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(_content(report).get("rows") or [])


def _todo(
    *,
    group: str,
    item: str,
    status: str,
    impact: str,
    risk: str,
    dependency: str,
    ack_required: bool,
    can_build_now: bool,
    bundle_with: Iterable[str],
    order: int,
) -> Dict[str, Any]:
    return {
        "group": group,
        "item": item,
        "status": status,
        "impact": impact,
        "risk": risk,
        "dependency": dependency,
        "ack_required": ack_required,
        "can_be_built_non_live_now": can_build_now,
        "bundle_with": list(bundle_with),
        "proposed_order": order,
    }


def build_remaining_workflow_todo_overview(
    *,
    dataset_plan: Dict[str, Any],
    readiness_matrix: Dict[str, Any],
    scaffold: Dict[str, Any],
    guardrails: Dict[str, Any],
    workflow_equivalence: Dict[str, Any],
    readiness_v3: Dict[str, Any],
) -> Dict[str, Any]:
    matrix = _content(readiness_matrix)
    dataset = _content(dataset_plan)
    ready = _content(readiness_v3)
    baseline_possible = set((matrix.get("summary") or {}).get("baseline_possible_tickers") or [])
    blocked_tickers = list((matrix.get("summary") or {}).get("blocked_tickers") or [])
    missing_rows = int(dataset.get("missing_row_count") or 0)
    todos = [
        _todo(group="P0 safety/blockers", item="Maintain no-open-order/no-D3-exit state before live prompt", status="done", impact="P0", risk="low", dependency="local safety checks", ack_required=False, can_build_now=False, bundle_with=["final safety checks"], order=1),
        _todo(group="P0 safety/blockers", item="Keep all live boundaries ACK-gated", status="done", impact="P0", risk="low", dependency="operator ACK", ack_required=True, can_build_now=False, bundle_with=["future live prompt"], order=2),
        _todo(group="P1 data coverage", item="Fetch missing 1H/4H/1D cached candles for all configured tickers", status="blocked", impact="high", risk="medium", dependency=DATA_FETCH_ACK, ack_required=True, can_build_now=False, bundle_with=["dataset quality", "backtest inputs"], order=3),
        _todo(group="P1 data coverage", item="Maintain dry-run/fetch command package", status="done", impact="high", risk="low", dependency="none", ack_required=False, can_build_now=True, bundle_with=["fetch ACK package"], order=4),
        _todo(group="P2 dataset quality", item="Run quality reports for fetched candle files", status="blocked", impact="high", risk="low", dependency="cached candle files", ack_required=False, can_build_now=False, bundle_with=["backtest execution"], order=5),
        _todo(group="P3 cached backtesting", item="Run baseline/cost/split-aware backtests for all tickers after data exists", status="blocked", impact="high", risk="low", dependency="dataset quality", ack_required=False, can_build_now=False, bundle_with=["backtest package"], order=6),
        _todo(group="P4 backlearning/parameter-review readiness", item="Keep parameter candidate scaffold human-review-only", status="done", impact="high", risk="low", dependency="none", ack_required=False, can_build_now=True, bundle_with=["guardrails"], order=7),
        _todo(group="P4 backlearning/parameter-review readiness", item="Real parameter optimization discussion", status="blocked", impact="high", risk="high", dependency="complete evidence plus future governance task", ack_required=True, can_build_now=False, bundle_with=["human review"], order=8),
        _todo(group="P5 multi-ticker workflow equivalence", item="Bring non-BTC tickers to BTC-USDC evidence parity", status="blocked", impact="high", risk="medium", dependency="data, backtests, lifecycle evidence", ack_required=True, can_build_now=False, bundle_with=["future controlled pilots"], order=9),
        _todo(group="P6 live-test evidence/preflight", item="BTC-USDC-only 24h preflight package", status="partial", impact="high", risk="medium", dependency="fresh safety checks and exact live ACKs", ack_required=True, can_build_now=True, bundle_with=["master packet"], order=10),
        _todo(group="P7 docs/context/roadmap", item="Keep roadmap/context synchronized", status="done", impact="medium", risk="low", dependency="none", ack_required=False, can_build_now=True, bundle_with=["all reports"], order=11),
        _todo(group="P8 optional technical debt", item="Stale denormalized reservation preview design", status="not_started", impact="medium", risk="medium", dependency="separate repair-preview task", ack_required=False, can_build_now=True, bundle_with=["local hygiene"], order=12),
    ]
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "remaining_workflow_todo_overview_v1",
        "status": "remaining_workflow_todo_overview_ready",
        "summary": {
            "missing_dataset_rows": missing_rows,
            "baseline_possible_tickers": sorted(baseline_possible),
            "blocked_tickers": blocked_tickers,
            "btc_usdc_route_status": ((ready.get("routes") or {}).get("btc_usdc_only_24h") or {}).get("status"),
            "all_ticker_route_status": ((ready.get("routes") or {}).get("all_ticker_24h") or {}).get("status"),
        },
        "todo_items": todos,
        "sprint_plan": {
            "sprint_1_now_no_ack": ["remaining planner packages", "docs/context/roadmap", "report validation"],
            "sprint_2_cached_local": ["BTC-USDC cached-only reporting", "local quality/backtest refresh when cached files exist"],
            "sprint_3_data_fetch_ack": ["bounded multi-ticker candle fetch", "dataset quality generation"],
            "sprint_4_after_data_backtests": ["all-ticker cached backtest reports", "workflow equivalence refresh"],
            "sprint_5_live_test_preparation": ["fresh BTC-USDC preflight", "exact ACK prompt"],
            "sprint_6_later_live_pilot": ["one controlled BTC-USDC 24h run only after ACKs"],
        },
        **_safety_flags(),
    }


def build_remaining_workflow_execution_plan(*, overview: Dict[str, Any]) -> Dict[str, Any]:
    items = list(overview.get("todo_items") or [])
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "remaining_workflow_execution_plan_v1",
        "status": "remaining_workflow_execution_plan_ready",
        "route_scores": [
            {"route": "A_overview_only", "safety": 10, "closure": 3, "speed": 3, "testability": 8, "boundary_risk": 1, "reuse_18_tickers": 5},
            {"route": "B_overview_docs_fixes", "safety": 10, "closure": 5, "speed": 5, "testability": 8, "boundary_risk": 1, "reuse_18_tickers": 6},
            {"route": "C_overview_plus_packages", "safety": 9, "closure": 9, "speed": 9, "testability": 8, "boundary_risk": 1, "reuse_18_tickers": 9},
        ],
        "chosen_route": "C_overview_plus_packages",
        "ordered_items": sorted(items, key=lambda row: int(row.get("proposed_order") or 999)),
        "next_non_live_step": "review generated packages and decide whether to ACK data fetch or proceed BTC-USDC-only",
        **_safety_flags(),
    }


def build_data_fetch_ack_package(*, dataset_plan: Dict[str, Any]) -> Dict[str, Any]:
    content = _content(dataset_plan)
    missing = [row for row in content.get("rows") or [] if row.get("missing_data_blocker")]
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "data_fetch_ack_package_v1",
        "status": "data_fetch_ack_package_ready_ack_required",
        "required_ack": DATA_FETCH_ACK,
        "max_chunks": 2,
        "missing_row_count": len(missing),
        "rows": [
            {
                "ticker": row["ticker"],
                "timeframe": row["timeframe"],
                "dry_run_command": (row.get("future_fetch_command") or {}).get("dry_run"),
                "fetch_command_after_ack": (row.get("future_fetch_command") or {}).get("fetch_after_ack"),
                "expected_output_path": f"research_data/coinbase/candles/product={row['ticker']}/timeframe={row['timeframe']}/",
                "state_write_performed": False,
            }
            for row in missing
        ],
        **_safety_flags(),
    }


def build_backtest_execution_package(*, readiness_matrix: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    for row in _rows(readiness_matrix):
        ticker = row["ticker"]
        for timeframe in ["1H", "4H", "1D"]:
            candle_path = f"research_data/coinbase/candles/product={ticker}/timeframe={timeframe}/study_window=3y.json"
            rows.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "dataset_quality_command": f".venv/bin/python tools/show_phase_d6_dataset_quality.py --candles {candle_path} --json",
                    "baseline_command": f".venv/bin/python tools/build_phase_d6_baseline_report_bundle.py --candles {candle_path} --output reports/d6/baseline-{ticker.lower()}-{timeframe.lower()}-20260601.json",
                    "cost_aware_baseline_command": f".venv/bin/python tools/build_phase_d6_cost_aware_baseline_bundle.py --candles {candle_path} --cost-scenario standard_fee_only --output reports/d6/cost-aware-{ticker.lower()}-{timeframe.lower()}-20260601.json",
                    "split_aware_baseline_command": f".venv/bin/python tools/show_phase_d6_split_aware_baseline.py --candles {candle_path} --json",
                    "expected_report_outputs": [
                        f"reports/d6/dataset-quality-{ticker.lower()}-{timeframe.lower()}-20260601.json",
                        f"reports/d6/baseline-{ticker.lower()}-{timeframe.lower()}-20260601.json",
                        f"reports/d6/cost-aware-{ticker.lower()}-{timeframe.lower()}-20260601.json",
                    ],
                    "no_optimization": True,
                    "parameter_review_allowed": False,
                    "ranking_performed": False,
                    "learning_to_execution_enabled": False,
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "backtest_execution_package_v1",
        "status": "backtest_execution_package_ready",
        "rows": rows,
        "blocked_until_data_exists": True,
        **_safety_flags(),
    }


def build_backlearning_review_package(*, scaffold: Dict[str, Any], guardrails: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "backlearning_review_package_v1",
        "status": "backlearning_review_package_ready_blocked",
        "required_evidence_before_parameter_review": [
            "complete_1h_4h_1d_dataset_quality",
            "cached_baseline_reports",
            "cost_aware_and_split_aware_reports",
            "oos_holdout_labels",
            "trial_accounting_limits",
            "fill_realism_evidence",
            "human_review_task_ack",
        ],
        "scaffold_summary": (_content(scaffold).get("summary") or {}),
        "guardrail_summary": (_content(guardrails).get("summary") or {}),
        "explicit_blockers": {
            "parameter_review_approved": False,
            "parameter_values_changed": False,
            "optimization_performed": False,
            "learning_to_execution_enabled": False,
        },
        **_safety_flags(),
    }


def build_multi_ticker_workflow_completion_checklist(
    *,
    readiness_matrix: Dict[str, Any],
    workflow_equivalence: Dict[str, Any],
) -> Dict[str, Any]:
    matrix = {row["ticker"]: row for row in _rows(readiness_matrix)}
    equivalence = {row["ticker"]: row for row in _rows(workflow_equivalence)}
    rows = []
    for ticker, row in matrix.items():
        eq = equivalence.get(ticker, {})
        missing = list(row.get("required_timeframes_missing") or [])
        rows.append(
            {
                "ticker": ticker,
                "configured": True,
                "candles_1h": "1H" not in missing,
                "candles_4h": "4H" not in missing,
                "candles_1d": "1D" not in missing,
                "dataset_quality": bool(row.get("dataset_quality_present")),
                "cached_baseline": bool(row.get("baseline_backtest_possible")),
                "cost_aware_baseline": bool(row.get("baseline_backtest_possible")),
                "split_aware_baseline": bool(row.get("baseline_backtest_possible")),
                "fill_realism_assumptions": bool(row.get("fill_realism_evidence_present")),
                "backlearning_guardrails": True,
                "d2_d3_compatibility": bool(eq.get("open_order_safety_compatibility")),
                "lifecycle_evidence": bool(eq.get("lifecycle_evidence")),
                "readiness_for_controlled_tiny_live_pilot": eq.get("readiness_for_future_controlled_live_pilot"),
                "readiness_for_24h_inclusion": "blocked" if eq.get("blockers_before_ticker_can_join_24h_live_test") else "ack_gated",
                "blockers": list(eq.get("blockers_before_ticker_can_join_24h_live_test") or []),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "multi_ticker_workflow_completion_checklist_v1",
        "status": "multi_ticker_workflow_completion_checklist_ready",
        "rows": rows,
        "summary": {
            "ticker_count": len(rows),
            "ready_for_24h_inclusion_count": sum(1 for row in rows if row["readiness_for_24h_inclusion"] != "blocked"),
            "blocked_count": sum(1 for row in rows if row["readiness_for_24h_inclusion"] == "blocked"),
        },
        **_safety_flags(),
    }


def build_future_24h_readiness_master_packet(
    *,
    overview: Dict[str, Any],
    execution_plan: Dict[str, Any],
    fetch_package: Dict[str, Any],
    backtest_package: Dict[str, Any],
    backlearning_package: Dict[str, Any],
    checklist: Dict[str, Any],
    readiness_v3: Dict[str, Any],
    state_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    ready = _content(readiness_v3)
    return {
        "generated_at": now_iso(),
        "phase": D6_REMAINING_WORK_PLANNER_PHASE,
        "report_name": "future_24h_readiness_master_packet_v1",
        "status": "future_24h_readiness_master_packet_ready",
        "current_safety_state": {"state_hashes": dict(state_hashes or {}), "live_action_authorized": False},
        "todo_summary": overview.get("summary", {}),
        "execution_plan_summary": {"chosen_route": execution_plan.get("chosen_route"), "next_non_live_step": execution_plan.get("next_non_live_step")},
        "fetch_package_summary": {"missing_row_count": fetch_package.get("missing_row_count"), "required_ack": fetch_package.get("required_ack")},
        "backtest_package_summary": {"row_count": len(backtest_package.get("rows") or []), "blocked_until_data_exists": backtest_package.get("blocked_until_data_exists")},
        "backlearning_package_summary": backlearning_package.get("explicit_blockers", {}),
        "per_ticker_checklist_summary": checklist.get("summary", {}),
        "btc_usdc_only_route": (ready.get("routes") or {}).get("btc_usdc_only_24h"),
        "all_ticker_route": (ready.get("routes") or {}).get("all_ticker_24h"),
        "acks": [DATA_FETCH_ACK, BTC_READ_ACK, BTC_SUBMIT_ACK, BTC_APPLY_ACK],
        "stop_conditions": ["no_coinbase_without_ack", "no_live_order_without_ack", "no_parameter_change", "no_learning_to_execution"],
        **_safety_flags(),
    }


__all__ = [
    "build_backlearning_review_package",
    "build_backtest_execution_package",
    "build_data_fetch_ack_package",
    "build_future_24h_readiness_master_packet",
    "build_multi_ticker_workflow_completion_checklist",
    "build_remaining_workflow_execution_plan",
    "build_remaining_workflow_todo_overview",
]
