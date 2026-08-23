from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PHASE_ALL_TICKER_READINESS_GATE = "all_ticker_readiness_gate_v1"
PROVEN_TINY_TICKER = "BTC-USDC"
DEFAULT_CONFIGURED_TICKERS = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "ADA-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "DOGE-USDC",
    "SUI-USDC",
    "LTC-USDC",
    "HBAR-USDC",
    "ATOM-USDC",
    "NEAR-USDC",
    "APT-USDC",
    "INJ-USDC",
    "ARB-USDC",
    "OP-USDC",
    "UNI-USDC",
]
OPEN_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "open",
    "active",
    "new",
    "queued",
    "partially_filled",
    "partial",
    "cancel_pending",
    "replace_pending",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _content(payload: Dict[str, Any]) -> Dict[str, Any]:
    inner = payload.get("content")
    return inner if isinstance(inner, dict) else payload


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _configured_tickers_from_config(root: Path) -> List[str]:
    path = root / "bot" / "config.py"
    if not path.exists():
        return list(DEFAULT_CONFIGURED_TICKERS)
    text = path.read_text(encoding="utf-8", errors="replace")
    out: List[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Z0-9]+-USDC\b", text):
        ticker = _normalize_ticker(match.group(0))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out or list(DEFAULT_CONFIGURED_TICKERS)


def orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("orders", payload)
    if isinstance(raw, dict):
        return [dict(order) for order in raw.values() if isinstance(order, dict)]
    if isinstance(raw, list):
        return [dict(order) for order in raw if isinstance(order, dict)]
    return []


def positions_from_payload(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = payload.get("positions", payload)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                ticker = _normalize_ticker(value.get("ticker") or key)
                if ticker:
                    out[ticker] = dict(value)
    elif isinstance(raw, list):
        for value in raw:
            if isinstance(value, dict):
                ticker = _normalize_ticker(value.get("ticker"))
                if ticker:
                    out[ticker] = dict(value)
    return out


def _is_open_order(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").strip().lower() in OPEN_STATUSES


def _is_d3_exit_order(order: Dict[str, Any]) -> bool:
    if str(order.get("side") or "").strip().upper() != "SELL":
        return False
    phase = str(order.get("phase") or "").strip()
    cid = str(order.get("client_order_id") or "").strip().lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return (
        phase == "D3_controlled_live_reduce_only_exits"
        or cid.startswith("phased3-")
        or cid.startswith("phased4-")
        or "d3" in mode
    )


def _source_status(root: Path, rel: str) -> Dict[str, Any]:
    path = root / rel
    return {"path": rel, "available": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}


def _reports(root: Path) -> Dict[str, Dict[str, Any]]:
    paths = {
        "safe_regression_harness": "reports/d6/safe-regression-harness-20260609.json",
        "d5_d6_evidence_expansion": "reports/d6/d5-d6-evidence-expansion-20260609.json",
        "exit_workflow_readiness": "reports/d6/exit-workflow-readiness-report-20260609.json",
        "core_lifecycle_evidence_gap": "reports/d6/core-lifecycle-evidence-gap-report-20260609.json",
        "c4_d1_handoff_branch_map": "reports/d6/c4-d1-handoff-branch-map-20260609.json",
        "workflow_ticker_coverage_audit": "reports/d6/workflow-ticker-coverage-audit-20260601.json",
        "coverage_backtest_decision": "reports/d6/coverage-backtest-decision-v1-20260601.json",
        "multi_ticker_workflow_equivalence": "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
        "multi_ticker_completion_checklist": "reports/d6/multi-ticker-workflow-completion-checklist-20260601.json",
        "btc_readonly_prelive": "reports/d6/24h-readiness-master-packet-readonly-prelive-v1-20260602.json",
        "replication_golden_payloads": "reports/d6/replication-lifecycle-golden-payloads-20260609.json",
    }
    return {key: _load_json(root / rel) for key, rel in paths.items()}


def _source_list(root: Path) -> List[Dict[str, Any]]:
    return [
        _source_status(root, rel)
        for rel in (
            "bot/config.py",
            "run_trader_loop.py",
            "state/open_orders.json",
            "state/positions.json",
            "reports/d6/safe-regression-harness-20260609.json",
            "reports/d6/d5-d6-evidence-expansion-20260609.json",
            "reports/d6/exit-workflow-readiness-report-20260609.json",
            "reports/d6/core-lifecycle-evidence-gap-report-20260609.json",
            "reports/d6/c4-d1-handoff-branch-map-20260609.json",
            "reports/d6/workflow-ticker-coverage-audit-20260601.json",
            "reports/d6/coverage-backtest-decision-v1-20260601.json",
            "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
            "reports/d6/multi-ticker-workflow-completion-checklist-20260601.json",
            "reports/d6/24h-readiness-master-packet-readonly-prelive-v1-20260602.json",
            "reports/d6/replication-lifecycle-golden-payloads-20260609.json",
        )
    ]


def _rows_by_ticker(payload: Dict[str, Any], rows_key: str = "rows") -> Dict[str, Dict[str, Any]]:
    rows = _content(payload).get(rows_key)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                ticker = _normalize_ticker(row.get("ticker"))
                if ticker:
                    out[ticker] = dict(row)
    return out


def _workflow_audit_rows(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = _content(payload).get("ticker_coverage_table")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                ticker = _normalize_ticker(row.get("ticker"))
                if ticker:
                    out[ticker] = dict(row)
    return out


def _status_from_bool(value: Any, *, true_status: str, false_status: str) -> str:
    if value is True:
        return true_status
    if value is False:
        return false_status
    return "unknown"


def _data_status(ticker: str, eq_row: Dict[str, Any], coverage_payload: Dict[str, Any]) -> str:
    coverage = bool(eq_row.get("candle_coverage_1h_4h_1d"))
    coverage_decision = _content(coverage_payload).get("backtest_decision") or {}
    normal_deferred = bool(coverage_decision.get("normal_backtests_deferred"))
    if coverage and normal_deferred:
        return "partial"
    if coverage:
        return "ready"
    return "missing" if eq_row else "unknown"


def _product_rule_status(ticker: str, prelive_payload: Dict[str, Any], eq_row: Dict[str, Any]) -> str:
    prelive = _content(prelive_payload)
    product_rules = ((prelive.get("preflight") or {}).get("product_rules") or {})
    if ticker == PROVEN_TINY_TICKER and product_rules.get("coherent_for_future_scope_review") is True:
        return "ready"
    if eq_row.get("product_rules_availability_source_local") is False:
        return "missing"
    return "unknown"


def _ticker_blockers(
    *,
    ticker: str,
    data_status: str,
    product_rule_status: str,
    c4_status: str,
    d1_status: str,
    d2_status: str,
    d3_status: str,
    d4_status: str,
    d5_status: str,
    replication_status: str,
) -> List[str]:
    blockers: List[str] = []
    if ticker != PROVEN_TINY_TICKER:
        blockers.append("outside_btc_usdc_tiny_scope")
        blockers.append("missing_live_lifecycle_evidence")
    if data_status == "unknown":
        blockers.append("data_coverage_unknown")
    if data_status not in {"ready", "partial"}:
        blockers.append("missing_local_data_coverage")
    if data_status == "partial":
        blockers.append("data_coverage_warning_only_not_normal_backtest_ready")
    if product_rule_status == "unknown":
        blockers.append("product_rule_status_unknown")
    if product_rule_status != "ready":
        blockers.append("missing_local_product_rules")
    for name, status in (
        ("c4_entry_lifecycle", c4_status),
        ("d1_fill_to_position", d1_status),
        ("d2_plan", d2_status),
        ("d3_exit", d3_status),
        ("d4_cancel_replace", d4_status),
        ("d5_d6_evidence", d5_status),
    ):
        if status in {"missing", "unknown"}:
            blockers.append(f"{name}_{status}")
        elif status == "partial":
            blockers.append(f"{name}_partial")
    if replication_status != "paper_only":
        blockers.append("replication_follower_not_live_ready")
    return sorted(set(blockers))


def _ticker_matrix(
    *,
    tickers: Sequence[str],
    reports: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    workflow_rows = _workflow_audit_rows(reports["workflow_ticker_coverage_audit"])
    eq_rows = _rows_by_ticker(reports["multi_ticker_workflow_equivalence"])
    d5_ready = bool(
        ((_content(reports["d5_d6_evidence_expansion"]).get("readiness_and_governance_flags") or {}).get(
            "d5_d6_evidence_expansion_ready"
        ))
    )
    golden = _content(reports["replication_golden_payloads"])
    follower_paper = bool(golden.get("follower_ready_for_paper_lifecycle_test") or golden.get("simulator_validation_passed"))
    rows: List[Dict[str, Any]] = []
    for ticker in tickers:
        eq = eq_rows.get(ticker, {})
        workflow = workflow_rows.get(ticker, {})
        data_status = _data_status(ticker, eq, reports["coverage_backtest_decision"])
        product_status = _product_rule_status(ticker, reports["btc_readonly_prelive"], eq)
        is_btc = ticker == PROVEN_TINY_TICKER
        live_evidence = bool(eq.get("lifecycle_evidence") or workflow.get("live_lifecycle_evidence_present"))
        c4_status = "proven" if is_btc and bool(eq.get("entry_workflow_evidence")) else "missing"
        d1_status = "partial" if is_btc and live_evidence else "missing"
        d2_status = "partial" if is_btc and bool(eq.get("d2_d3_workflow_evidence")) else "missing"
        d3_status = "proven" if is_btc and bool(eq.get("d2_d3_workflow_evidence")) else "missing"
        d4_status = "proven" if is_btc and bool(eq.get("lifecycle_evidence")) else "missing"
        d5_status = "ready" if is_btc and d5_ready else ("partial" if bool(eq.get("candle_coverage_1h_4h_1d")) else "missing")
        replication_status = "paper_only" if follower_paper else "missing"
        blockers = _ticker_blockers(
            ticker=ticker,
            data_status=data_status,
            product_rule_status=product_status,
            c4_status=c4_status,
            d1_status=d1_status,
            d2_status=d2_status,
            d3_status=d3_status,
            d4_status=d4_status,
            d5_status=d5_status,
            replication_status=replication_status,
        )
        rows.append(
            {
                "ticker": ticker,
                "data_coverage_status": data_status,
                "product_rule_status": product_status,
                "live_workflow_evidence_status": "proven" if live_evidence and is_btc else ("missing" if not live_evidence else "partial"),
                "c4_entry_lifecycle_status": c4_status,
                "d1_fill_to_position_status": d1_status,
                "d2_plan_status": d2_status,
                "d3_exit_status": d3_status,
                "d4_cancel_replace_status": d4_status,
                "d5_d6_evidence_status": d5_status,
                "replication_follower_status": replication_status,
                "all_ticker_live_status": "blocked" if blockers else "ready",
                "blockers": blockers,
                "what_would_make_ready": _what_would_make_ready(ticker, blockers),
            }
        )
    return rows


def _what_would_make_ready(ticker: str, blockers: Sequence[str]) -> List[str]:
    if not blockers:
        return ["already_report_ready_but_live_still_requires_exact_ack"]
    out: List[str] = []
    if "outside_btc_usdc_tiny_scope" in blockers:
        out.append("separate all-ticker scope design and exact ACK")
    if "missing_local_product_rules" in blockers:
        out.append("local product-rule evidence for this ticker")
    if "data_coverage_warning_only_not_normal_backtest_ready" in blockers or "missing_local_data_coverage" in blockers:
        out.append("accepted local data quality/backtest-readiness evidence")
    if "missing_live_lifecycle_evidence" in blockers:
        out.append("paper then controlled live lifecycle evidence equivalent to BTC-USDC")
    lifecycle_blockers = [b for b in blockers if b.startswith(("c4_", "d1_", "d2_", "d3_", "d4_", "d5_"))]
    if lifecycle_blockers:
        out.append("per-stage lifecycle evidence for C4/D1/D2/D3/D4/D5")
    if "replication_follower_not_live_ready" in blockers:
        out.append("follower receiver/API and paper-to-live readiness")
    return sorted(set(out))


def _configured_universe(tickers: Sequence[str]) -> List[Dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "configured": True,
            "currently_allowed_for_tiny_run": ticker == PROVEN_TINY_TICKER,
            "allowed_for_all_ticker_live": False,
            "reason": "BTC-USDC tiny-run scope only" if ticker == PROVEN_TINY_TICKER else "configured but not in BTC-USDC tiny-run scope",
        }
        for ticker in tickers
    ]


def _btc_scope_status(matrix: Sequence[Dict[str, Any]], reports: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    btc = next((row for row in matrix if row.get("ticker") == PROVEN_TINY_TICKER), {})
    safe = _content(reports["safe_regression_harness"])
    flags = safe.get("readiness_flags") or {}
    prelive = _content(reports["btc_readonly_prelive"])
    go_no_go = prelive.get("go_no_go_matrix") or {}
    return {
        "btc_usdc_tiny_scope_ready_for_operator_preflight": bool(flags.get("master_ready_for_operator_preflight", True))
        and btc.get("ticker") == PROVEN_TINY_TICKER,
        "btc_usdc_live_workflow_evidence_status": btc.get("live_workflow_evidence_status", "unknown"),
        "btc_usdc_blockers": list(btc.get("blockers") or []),
        "btc_usdc_is_only_operator_ready_tiny_scope": True,
        "prelive_status": go_no_go.get("final_status") or prelive.get("status"),
        "not_live_ready_reason": go_no_go.get("not_ready_for_live_reason", "fresh_preflight_and_exact_live_ack_missing"),
    }


def _current_state_guard(orders: Sequence[Dict[str, Any]], positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    open_orders = [order for order in orders if _is_open_order(order)]
    open_d3 = [order for order in open_orders if _is_d3_exit_order(order)]
    active_positions = [
        ticker
        for ticker, position in positions.items()
        if str(position.get("status") or "").strip().lower() in {"open", "active"}
    ]
    stop_reasons: List[str] = []
    if open_orders:
        stop_reasons.append("open_orders_present")
    if open_d3:
        stop_reasons.append("open_d3_exit_present")
    return {
        "open_orders": len(open_orders),
        "open_d3_exit": len(open_d3),
        "active_positions": sorted(active_positions),
        "stop_reasons": stop_reasons,
    }


def build_all_ticker_readiness_gate_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    configured_tickers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    source_tickers = _configured_tickers_from_config(project_root) if configured_tickers is None else list(configured_tickers)
    tickers = [_normalize_ticker(ticker) for ticker in source_tickers]
    tickers = [ticker for ticker in tickers if ticker]
    reports = _reports(project_root)
    orders = orders_from_payload(_load_json(project_root / "state" / "open_orders.json"))
    positions = positions_from_payload(_load_json(project_root / "state" / "positions.json"))
    state_guard = _current_state_guard(orders, positions)

    matrix = _ticker_matrix(tickers=tickers, reports=reports) if tickers else []
    universe = _configured_universe(tickers)
    btc_scope = _btc_scope_status(matrix, reports) if tickers else {
        "btc_usdc_tiny_scope_ready_for_operator_preflight": False,
        "btc_usdc_live_workflow_evidence_status": "unknown",
        "btc_usdc_blockers": ["configured_universe_empty_or_malformed"],
        "btc_usdc_is_only_operator_ready_tiny_scope": False,
        "prelive_status": "unknown",
        "not_live_ready_reason": "configured_universe_empty_or_malformed",
    }

    tickers_ready = [row for row in matrix if row.get("all_ticker_live_status") == "ready"]
    tickers_blocked = [row for row in matrix if row.get("all_ticker_live_status") == "blocked"]
    missing_evidence = [
        row
        for row in matrix
        if any("missing" in str(blocker) or "unknown" in str(blocker) for blocker in row.get("blockers") or [])
    ]
    all_blockers = sorted({blocker for row in matrix for blocker in (row.get("blockers") or [])})
    if not tickers:
        all_blockers.append("configured_universe_empty_or_malformed")

    if state_guard["stop_reasons"] or not tickers:
        classification = "STOP_NOW"
    elif all_blockers or len(tickers_ready) < len(tickers):
        classification = "WATCH"
    else:
        classification = "OK"

    all_ticker_ready = bool(tickers) and not all_blockers and len(tickers_ready) == len(tickers)
    flags = {
        "local_safe_regression_passed": bool((_content(reports["safe_regression_harness"]).get("local_safe_regression_passed"))),
        "btc_usdc_tiny_scope_ready_for_operator_preflight": bool(
            btc_scope.get("btc_usdc_tiny_scope_ready_for_operator_preflight")
        ),
        "master_ready_for_operator_preflight": bool(
            ((_content(reports["safe_regression_harness"]).get("readiness_flags") or {}).get(
                "master_ready_for_operator_preflight",
                False,
            ))
        ),
        "master_ready_for_operator_live_start": False,
        "master_live_exit_ready": False,
        "follower_ready_for_paper_lifecycle_test": bool(
            ((_content(reports["safe_regression_harness"]).get("readiness_flags") or {}).get(
                "follower_ready_for_paper_lifecycle_test",
                False,
            ))
        ),
        "follower_ready_for_live": False,
        "follower_sell_ready": False,
        "lifecycle_parity_ready": False,
        "all_ticker_ready": all_ticker_ready,
        "all_ticker_live_allowed_now": False,
        "learning_to_execution_ready": False,
        "parameter_change_allowed": False,
        "parameter_review_approved": False,
        "state_hygiene_cleanup_preview_ready": bool(
            ((_content(reports["safe_regression_harness"]).get("readiness_flags") or {}).get(
                "state_hygiene_cleanup_preview_ready",
                False,
            ))
        ),
        "state_hygiene_apply_ready": False,
    }

    return _json_safe(
        {
            "phase": PHASE_ALL_TICKER_READINESS_GATE,
            "generated_at": generated_at or _now_iso(),
            "report_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_replication_call_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_attempted": False,
            "classification": classification,
            "evidence_sources_inspected": _source_list(project_root),
            "configured_universe": {
                "source": "bot/config.py default ALLOWED_TICKERS",
                "ticker_count": len(tickers),
                "tickers": tickers,
                "rows": universe,
            },
            "btc_usdc_scope_status": btc_scope,
            "per_ticker_readiness_matrix": matrix,
            "gate_decision": {
                "all_ticker_ready": all_ticker_ready,
                "all_ticker_live_allowed_now": False,
                "all_ticker_blockers": sorted(set(all_blockers)),
                "tickers_ready_count": len(tickers_ready),
                "tickers_blocked_count": len(tickers_blocked),
                "tickers_missing_evidence_count": len(missing_evidence),
                "recommended_next_steps": [
                    "audit follower receiver/API if accessible",
                    "expand safe regression harness selected tests",
                    "only run fresh BTC-USDC preflight/live-start decision pack after explicit operator intent",
                ],
            },
            "current_state_guard": state_guard,
            "safety_distinctions": {
                "btc_usdc_tiny_readiness_does_not_imply_all_ticker_readiness": True,
                "report_only_gate_does_not_authorize_live_trading": True,
                "all_ticker_live_requires_separate_exact_ack": True,
                "non_btc_live_requires_product_rules_data_lifecycle_and_ack": True,
                "live_sell_separate_from_live_buy": True,
                "follower_live_separate_from_master_live": True,
                "learning_to_execution_ready": False,
            },
            "readiness_flags": flags,
        }
    )


def render_all_ticker_readiness_gate_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("readiness_flags") or {}
    gate = report.get("gate_decision") or {}
    btc = report.get("btc_usdc_scope_status") or {}
    lines = [
        "# All-Ticker Readiness Gate",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{report.get('report_only')}`",
        f"- coinbase_call_attempted: `{report.get('coinbase_call_attempted')}`",
        f"- market_data_fetch_attempted: `{report.get('market_data_fetch_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        "",
        "## Gate Decision",
        "",
        f"- btc_usdc_tiny_scope_ready_for_operator_preflight: `{btc.get('btc_usdc_tiny_scope_ready_for_operator_preflight')}`",
        f"- btc_usdc_live_workflow_evidence_status: `{btc.get('btc_usdc_live_workflow_evidence_status')}`",
        f"- btc_usdc_is_only_operator_ready_tiny_scope: `{btc.get('btc_usdc_is_only_operator_ready_tiny_scope')}`",
        f"- all_ticker_ready: `{gate.get('all_ticker_ready')}`",
        f"- all_ticker_live_allowed_now: `{gate.get('all_ticker_live_allowed_now')}`",
        f"- tickers_ready_count: `{gate.get('tickers_ready_count')}`",
        f"- tickers_blocked_count: `{gate.get('tickers_blocked_count')}`",
        f"- tickers_missing_evidence_count: `{gate.get('tickers_missing_evidence_count')}`",
        f"- all_ticker_blockers: `{'; '.join(gate.get('all_ticker_blockers') or [])}`",
        "",
        "## Per-Ticker Matrix",
        "",
        "| Ticker | Live Status | Data | Product Rules | C4 | D1 | D2 | D3 | D4 | D5/D6 | Blockers |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report.get("per_ticker_readiness_matrix") or []:
        blockers = "; ".join(row.get("blockers") or [])
        lines.append(
            "| {ticker} | {live} | {data} | {product} | {c4} | {d1} | {d2} | {d3} | {d4} | {d5} | {blockers} |".format(
                ticker=row.get("ticker"),
                live=row.get("all_ticker_live_status"),
                data=row.get("data_coverage_status"),
                product=row.get("product_rule_status"),
                c4=row.get("c4_entry_lifecycle_status"),
                d1=row.get("d1_fill_to_position_status"),
                d2=row.get("d2_plan_status"),
                d3=row.get("d3_exit_status"),
                d4=row.get("d4_cancel_replace_status"),
                d5=row.get("d5_d6_evidence_status"),
                blockers=blockers,
            )
        )
    lines.extend(["", "## Readiness Flags", ""])
    for key in (
        "local_safe_regression_passed",
        "btc_usdc_tiny_scope_ready_for_operator_preflight",
        "master_ready_for_operator_preflight",
        "master_ready_for_operator_live_start",
        "master_live_exit_ready",
        "follower_ready_for_paper_lifecycle_test",
        "follower_ready_for_live",
        "follower_sell_ready",
        "lifecycle_parity_ready",
        "all_ticker_ready",
        "all_ticker_live_allowed_now",
        "learning_to_execution_ready",
        "parameter_change_allowed",
        "parameter_review_approved",
        "state_hygiene_cleanup_preview_ready",
        "state_hygiene_apply_ready",
    ):
        lines.append(f"- {key}: `{flags.get(key)}`")
    lines.extend(
        [
            "",
            "## Safety Distinctions",
            "",
            "- BTC-USDC tiny readiness does not imply all-ticker readiness.",
            "- This report-only gate does not authorize live trading.",
            "- All-ticker live requires separate exact ACK.",
            "- Non-BTC tickers must not be live-enabled without product rules, data coverage, lifecycle evidence and operator ACK.",
            "- Live SELL remains separate from live BUY.",
            "- Follower live remains separate from master live.",
            "- Learning-to-execution remains false.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ALL_TICKER_READINESS_GATE",
    "build_all_ticker_readiness_gate_report",
    "render_all_ticker_readiness_gate_markdown",
]
