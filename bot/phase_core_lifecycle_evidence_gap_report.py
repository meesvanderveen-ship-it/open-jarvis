from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "core_lifecycle_evidence_gap_report_v1"


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
        "learning_to_execution_enabled": False,
    }


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _read_text(root: Path, rel: str, max_chars: int = 750_000) -> str:
    path = root / rel
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def _sha256(root: Path, rel: str) -> str:
    path = root / rel
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _json(root: Path, rel: str) -> Any:
    text = _read_text(root, rel)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _pattern_hits(root: Path, rels: Iterable[str], patterns: Iterable[str]) -> Dict[str, Any]:
    hits: Dict[str, List[str]] = {}
    for rel in rels:
        text = _read_text(root, rel)
        if not text:
            continue
        lower = text.lower()
        found = [pattern for pattern in patterns if pattern.lower() in lower]
        if found:
            hits[rel] = found
    return {
        "file_count": len(hits),
        "hits": hits,
    }


def _open_order_summary(root: Path) -> Dict[str, Any]:
    payload = _json(root, "state/open_orders.json")
    orders_obj = payload.get("orders", {}) if isinstance(payload, dict) else {}
    if isinstance(orders_obj, dict):
        orders = [row for row in orders_obj.values() if isinstance(row, dict)]
    elif isinstance(orders_obj, list):
        orders = [row for row in orders_obj if isinstance(row, dict)]
    else:
        orders = []
    open_statuses = {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending", "open"}
    by_status = Counter(str(order.get("status") or "unknown").lower() for order in orders)
    open_orders = [
        order for order in orders
        if str(order.get("status") or "").lower() in open_statuses
    ]
    open_d3 = [
        order for order in open_orders
        if str(order.get("side") or "").upper() == "SELL"
        and (
            str(order.get("client_order_id") or "").startswith("phased3-")
            or str(order.get("phase") or "") == "D3_controlled_live_reduce_only_exits"
            or str(order.get("source_mode") or "") == "phase_d3_live_exit"
        )
    ]
    return {
        "total_orders": len(orders),
        "open_orders": len(open_orders),
        "open_d3_exit": len(open_d3),
        "by_status": dict(by_status),
    }


def _position_summary(root: Path) -> Dict[str, Any]:
    payload = _json(root, "state/positions.json")
    positions = payload if isinstance(payload, dict) else {}
    btc = positions.get("BTC-USDC") if isinstance(positions.get("BTC-USDC"), dict) else {}
    return {
        "btc_usdc_position_size_base": str(btc.get("position_size_base") or ""),
        "btc_usdc_bot_managed_base": str(btc.get("bot_managed_base") or ""),
        "btc_usdc_reserved_base_open_exit_orders": str(btc.get("reserved_base_open_exit_orders") or ""),
        "btc_usdc_monitoring_enabled": btc.get("monitoring_enabled"),
        "position_count": len([value for value in positions.values() if isinstance(value, dict)]),
    }


def _row(
    *,
    area: str,
    status: str,
    priority: str,
    evidence: List[str],
    gap: str,
    risk_if_skipped: str,
    blocks_btc_24h: bool,
    blocks_full_workflow: bool,
    acceptance: List[str],
    expected_files: List[str],
    expected_tests: List[str],
    risk_type: str,
) -> Dict[str, Any]:
    return {
        "area": area,
        "status": status,
        "priority": priority,
        "evidence_found": evidence,
        "remaining_gap": gap,
        "risk_if_skipped": risk_if_skipped,
        "blocks_btc_24h": blocks_btc_24h,
        "blocks_full_workflow": blocks_full_workflow,
        "acceptance_criteria": acceptance,
        "expected_files_or_tools": expected_files,
        "expected_tests": expected_tests,
        "risk_type": risk_type,
    }


def _lifecycle_rows(root: Path) -> List[Dict[str, Any]]:
    c4_tests = _pattern_hits(
        root,
        [
            "tests/test_phase_c43_lifecycle_orchestrator.py",
            "tests/test_phase_c45_live_fill_pilot.py",
            "tests/test_phase_c44_poll_to_apply_closeout.py",
            "tests/test_phase_c43_controlled_entry_pilot.py",
        ],
        ["fill", "cancel", "rejected", "apply", "ack", "no_coinbase"],
    )
    d3_tests = _pattern_hits(
        root,
        [
            "tests/test_phase_d3_live_exit_reconciliation.py",
            "tests/test_phase_d3_controlled_live_exits.py",
            "tests/test_phase_d3_reservation_governance.py",
            "tests/test_phase_d45_lifecycle_simulation_hardening.py",
        ],
        ["partial", "filled", "cancelled", "duplicate", "oversell", "reservation", "ack"],
    )
    d4_tests = _pattern_hits(
        root,
        [
            "tests/test_phase_d4_trailing_preview.py",
            "tests/test_phase_d4_cancel_replace_planner.py",
            "tests/test_phase_d4_controlled_cancel_replace.py",
            "tests/test_phase_d3_cancel_replace_pilot.py",
        ],
        ["cancel", "replace", "trailing", "ack", "duplicate", "reservation"],
    )
    d5_tests = _pattern_hits(
        root,
        [
            "tests/test_phase_d5_execution_metrics.py",
            "tests/test_phase_d6_d5_evidence_adapter.py",
            "tests/test_phase_d6_fill_realism_evidence_adapter.py",
        ],
        ["latency", "slippage", "fill", "cancel_replace", "learning_to_execution"],
    )

    return [
        _row(
            area="C4_entry_order_lifecycle",
            status="partial_btc_proven",
            priority="P2",
            evidence=[
                "bot/phase_c43_autonomous_entry_live.py",
                "bot/phase_c43_lifecycle_orchestrator.py",
                "bot/phase_c44_poll_to_apply_closeout.py",
                f"test_evidence_files={c4_tests['file_count']}",
            ],
            gap="C4 branch evidence exists but is spread across tools/tests; no current consolidated branch matrix for operator review.",
            risk_if_skipped="A live fill/cancel/reject branch may require manual reconstruction under time pressure.",
            blocks_btc_24h=True,
            blocks_full_workflow=True,
            acceptance=[
                "single report maps C4 open/fill/partial/cancel/reject branches",
                "fill apply remains ACK-gated",
                "no Coinbase submit/cancel/replace from report path",
            ],
            expected_files=["bot/phase_c43_*", "bot/phase_c44_*", "bot/phase_c45_*"],
            expected_tests=["tests/test_phase_c43_*", "tests/test_phase_c44_*", "tests/test_phase_c45_*"],
            risk_type="read-only",
        ),
        _row(
            area="D1_fill_to_position_transition",
            status="partial_distributed",
            priority="P2",
            evidence=[
                "bot/phase_c45_live_fill_pilot.py",
                "bot/phase_d1_exit_orderbook_scaffold.py",
                "bot/phase_d3_live_exit_reconciliation.py",
            ],
            gap="D.1 is not a cohesive named fill-reconciliation stage; fill-to-position and exit readiness are distributed across C4.5, D1 scaffold and D3 reconciliation.",
            risk_if_skipped="The handoff from live fill evidence to position and exit planning can be misunderstood.",
            blocks_btc_24h=True,
            blocks_full_workflow=True,
            acceptance=[
                "explicit D1 handoff checklist exists",
                "position creation requires fill evidence and ACK",
                "D2/D3 preview is separated from live exit submit",
            ],
            expected_files=["bot/phase_c45_live_fill_pilot.py", "bot/phase_d1_exit_orderbook_scaffold.py"],
            expected_tests=["tests/test_phase_c45_live_fill_pilot.py", "tests/test_phase_d1_exit_orderbook_scaffold.py"],
            risk_type="read-only",
        ),
        _row(
            area="D2_position_executor",
            status="done_no_active_position",
            priority="P2",
            evidence=["bot/phase_d2_position_executor.py", "tests/test_phase_d2_position_executor.py"],
            gap="No active BTC-USDC position exists now, so next proof occurs only after a future fill apply.",
            risk_if_skipped="D3 could be previewed from stale or incoherent position context.",
            blocks_btc_24h=False,
            blocks_full_workflow=True,
            acceptance=[
                "D2 plan fingerprint present after fill apply",
                "fee-edge and no-averaging-down checks pass",
                "D3 preview consumes the same coherent position id",
            ],
            expected_files=["bot/phase_d2_position_executor.py", "state/phase_d2_position_executor_plans.json"],
            expected_tests=["tests/test_phase_d2_position_executor.py"],
            risk_type="read-only",
        ),
        _row(
            area="D3_controlled_exit_submit_and_reconcile",
            status="done_parked_warning_state_hygiene",
            priority="P2",
            evidence=[
                "bot/phase_d3_controlled_live_exits.py",
                "bot/phase_d3_live_exit_reconciliation.py",
                f"test_evidence_files={d3_tests['file_count']}",
            ],
            gap="D3 is implemented and current open exits are zero, but stale denormalized reservation and TP_CLOSE fee discrepancy remain documented warnings.",
            risk_if_skipped="A future exit could be prepared before reservation/base/fee evidence is understood.",
            blocks_btc_24h=False,
            blocks_full_workflow=True,
            acceptance=[
                "open_d3_exit remains zero before BTC tiny start",
                "future D3 apply requires exact evidence ACK",
                "reservation and duplicate-exit guards remain tested",
            ],
            expected_files=["bot/phase_d3_*", "tools/show_phase_d3_controlled_live_exits.py"],
            expected_tests=["tests/test_phase_d3_*", "tests/test_phase_d45_*"],
            risk_type="read-only",
        ),
        _row(
            area="D4_trailing_cancel_replace",
            status="partial_preview_only",
            priority="P2",
            evidence=[
                "bot/phase_d4_trailing_preview.py",
                "bot/phase_d4_cancel_replace_planner.py",
                f"test_evidence_files={d4_tests['file_count']}",
            ],
            gap="Preview/planner coverage exists, but production automation and live cancel/replace remain ACK-gated and not part of BTC tiny start.",
            risk_if_skipped="Future reprice/trailing could violate cancel-first or reservation sequencing.",
            blocks_btc_24h=False,
            blocks_full_workflow=True,
            acceptance=[
                "cancel-first sequencing documented",
                "no atomic cancel+replace",
                "replacement sizing remains reservation-aware",
            ],
            expected_files=["bot/phase_d4_*", "tools/show_phase_d4_*"],
            expected_tests=["tests/test_phase_d4_*", "tests/test_phase_d3_cancel_replace_*"],
            risk_type="read-only-now_live-risk-later",
        ),
        _row(
            area="D5_execution_metrics_and_evidence",
            status="partial_scaffolded",
            priority="P2",
            evidence=[
                "bot/phase_d5_execution_metrics.py",
                "bot/phase_d6_d5_evidence_adapter.py",
                f"test_evidence_files={d5_tests['file_count']}",
            ],
            gap="Metrics are descriptive scaffolds; a post-live official evidence bundle still needs real lifecycle inputs.",
            risk_if_skipped="Learning evidence may remain anecdotal or be overinterpreted.",
            blocks_btc_24h=False,
            blocks_full_workflow=True,
            acceptance=[
                "D5 evidence bundle consumes post-run lifecycle rows",
                "learning-to-execution remains false",
                "no parameter recommendations emitted",
            ],
            expected_files=["bot/phase_d5_execution_metrics.py", "bot/phase_d6_d5_evidence_adapter.py"],
            expected_tests=["tests/test_phase_d5_execution_metrics.py", "tests/test_phase_d6_d5_evidence_adapter.py"],
            risk_type="read-only",
        ),
    ]


def build_core_lifecycle_evidence_gap_report(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root).resolve()
    rows = _lifecycle_rows(project_root)
    open_orders = _open_order_summary(project_root)
    positions = _position_summary(project_root)
    status_counts = Counter(row["status"] for row in rows)
    priority_counts = Counter(row["priority"] for row in rows)
    btc_blockers = [row["area"] for row in rows if row["blocks_btc_24h"] and row["status"].startswith("missing")]
    btc_review_required = [row["area"] for row in rows if row["blocks_btc_24h"] and row["status"] != "done"]
    full_blockers = [row["area"] for row in rows if row["blocks_full_workflow"] and row["status"] != "done"]

    report = {
        "generated_at": now_iso(),
        "phase": PHASE,
        "status": "core_lifecycle_evidence_gap_report_ready",
        "route_chosen": "Route B - core lifecycle evidence hardening",
        "read_only": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "root": str(project_root),
        "current_state_evidence": {
            "open_orders": open_orders,
            "positions": positions,
            "state_hashes": {
                "state/open_orders.json": _sha256(project_root, "state/open_orders.json"),
                "state/positions.json": _sha256(project_root, "state/positions.json"),
            },
        },
        "summary": {
            "row_count": len(rows),
            "status_counts": dict(status_counts),
            "priority_counts": dict(priority_counts),
            "btc_24h_review_required_areas": btc_review_required,
            "btc_24h_hard_blockers_from_report": btc_blockers,
            "full_workflow_blocking_areas": full_blockers,
            "conclusion": (
                "BTC-USDC tiny run remains operator-ACK gated and locally startable after fresh safety checks, "
                "but C4/D1/D2/D3 evidence should be reviewed before the run because fill handling is the next core risk."
            ),
        },
        "workflow_rows": rows,
        "critical_gap_backlog": [
            {
                "id": "P0-CORE-001",
                "title": "Fresh local no-open-order/no-D3-exit safety check before operator run",
                "status": "done_but_must_repeat_at_runtime",
                "why_it_matters": "prevents duplicate/oversell/open-exit collision",
                "dependency": "operator preflight window",
                "acceptance_criteria": ["open_orders=0", "open_d3_exit=0", "function_audit=ok_observe_only", "state hashes captured"],
                "expected_files_tools_tests": ["tools/show_open_orders.py", "tools/show_phase_d3_controlled_live_exits.py", "tools/show_function_preservation_audit.py"],
                "risk_type": "read-only",
            },
            {
                "id": "P1-CORE-002",
                "title": "C4/D1 fill-to-position branch checklist before BTC tiny run",
                "status": "partial",
                "why_it_matters": "future fill evidence must not trigger unauthorized apply or premature D3 live exits",
                "dependency": "C4.5/C4.4/D1 evidence map",
                "acceptance_criteria": ["operator knows fill apply ACK boundary", "D2/D3 preview stays non-live", "no state write without evidence ACK"],
                "expected_files_tools_tests": ["bot/phase_c45_live_fill_pilot.py", "bot/phase_c44_poll_to_apply_closeout.py", "docs/OPERATOR_24H_LIVE_TEST_RUNBOOK.md"],
                "risk_type": "read-only",
            },
            {
                "id": "P2-CORE-003",
                "title": "D3 reservation/fee stale-field cleanup preview",
                "status": "not_started",
                "why_it_matters": "keeps local lifecycle evidence understandable without manual state edits",
                "dependency": "separate cleanup preview task; apply requires exact ACK",
                "acceptance_criteria": ["preview-only report", "no state write", "fee evidence preserved"],
                "expected_files_tools_tests": ["tools/preview_or_apply_phase_d3_reservation_repair.py", "state/positions.json"],
                "risk_type": "state-risk-if-applied",
            },
        ],
        "recommended_next_route": {
            "route": "Route A after this sprint",
            "title": "runbook/generated command consistency",
            "why": "core lifecycle review now defines the evidence surfaces that generated operator packs should reference",
        },
        **_safety_flags(),
    }
    return report


def render_core_lifecycle_evidence_gap_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    state = report.get("current_state_evidence") or {}
    open_orders = state.get("open_orders") or {}
    hashes = state.get("state_hashes") or {}
    lines = [
        "# Core Lifecycle Evidence Gap Report",
        "",
        "Read-only roadmap artifact. No Coinbase calls, no live action and no trading-state writes.",
        "",
        "## Summary",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- route_chosen: `{report.get('route_chosen')}`",
        f"- status: `{report.get('status')}`",
        f"- open_orders: `{open_orders.get('open_orders')}`",
        f"- open_d3_exit: `{open_orders.get('open_d3_exit')}`",
        f"- state/open_orders.json: `{hashes.get('state/open_orders.json')}`",
        f"- state/positions.json: `{hashes.get('state/positions.json')}`",
        f"- btc_24h_review_required_areas: `{', '.join(summary.get('btc_24h_review_required_areas') or []) or 'none'}`",
        f"- full_workflow_blocking_areas: `{', '.join(summary.get('full_workflow_blocking_areas') or []) or 'none'}`",
        "",
        "## Workflow Rows",
    ]
    for row in report.get("workflow_rows") or []:
        lines.extend(
            [
                f"### {row.get('area')}",
                f"- status: `{row.get('status')}`",
                f"- priority: `{row.get('priority')}`",
                f"- blocks_btc_24h: `{row.get('blocks_btc_24h')}`",
                f"- blocks_full_workflow: `{row.get('blocks_full_workflow')}`",
                f"- remaining_gap: {row.get('remaining_gap')}",
                f"- risk_if_skipped: {row.get('risk_if_skipped')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Recommended Next Route",
            f"- route: `{(report.get('recommended_next_route') or {}).get('route')}`",
            f"- title: `{(report.get('recommended_next_route') or {}).get('title')}`",
            f"- why: {(report.get('recommended_next_route') or {}).get('why')}",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "build_core_lifecycle_evidence_gap_report",
    "render_core_lifecycle_evidence_gap_markdown",
]
