#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.phase_c_live_guard import LIVE_ENTRY_GUARD_VERSION, LIVE_ENTRY_REQUIRED_GATES
from bot.product_rules import PRODUCT_RULE_NORMALIZER_VERSION


OPEN_ORDER_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}
OPEN_POSITION_TICKERS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        out = value if isinstance(value, Decimal) else Decimal(str(value))
        if out.is_nan() or out.is_infinite():
            return Decimal(default)
        return out
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _orders(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [dict(v) for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [dict(v) for v in payload if isinstance(v, dict)]
    return []


def _open_positions(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    out: List[Dict[str, Any]] = []
    for ticker, value in payload.items():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "").strip().lower()
        base = _to_decimal(value.get("bot_managed_base") or value.get("position_size_base") or value.get("base_size"), "0")
        if status == "open" and base > Decimal("0"):
            row = dict(value)
            row.setdefault("ticker", str(ticker).upper())
            out.append(row)
    return out


def _position_order_evidence(orders: Sequence[Dict[str, Any]], position: Dict[str, Any]) -> Dict[str, Any]:
    client_id = str(position.get("phase_c43_client_order_id") or "")
    exchange_id = str(position.get("phase_c43_exchange_order_id") or position.get("order_id") or "")
    for order in orders:
        if client_id and str(order.get("client_order_id") or "") == client_id:
            return order
        if exchange_id and str(order.get("exchange_order_id") or order.get("order_id") or "") == exchange_id:
            return order
    return {}


def _missing_position_evidence(position: Dict[str, Any], order: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not order:
        missing.append("local source order record")
    if not str(position.get("phase_c43_exchange_order_id") or position.get("order_id") or "").strip():
        missing.append("exchange order id")
    if _to_decimal(position.get("position_size_base") or position.get("bot_managed_base"), "0") <= Decimal("0"):
        missing.append("base size")
    if _to_decimal(position.get("entry_price"), "0") <= Decimal("0"):
        missing.append("avg entry")
    if _to_decimal(position.get("invalidation_price"), "0") <= Decimal("0"):
        missing.append("invalidation price")
    if str(position.get("protective_stop_status") or "") == "position_risk_incomplete":
        missing.append("complete protective stop state")
    if str(position.get("d2_plan_status") or "") != "ready":
        missing.append("ready D2 plan")
    if str(position.get("d3_exit_status") or "") != "ready":
        missing.append("ready D3 exit plan")
    if order and str(order.get("status") or "").lower() != "filled":
        missing.append("terminal fill evidence")
    return missing


def build_reconciliation_report(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    order_rows = _orders(_load_json(project_root / "state/open_orders.json"))
    position_rows = _open_positions(_load_json(project_root / "state/positions.json"))
    open_orders = [row for row in order_rows if str(row.get("status") or "").lower() in OPEN_ORDER_STATUSES]
    open_exits = [
        row for row in open_orders
        if str(row.get("side") or "").upper() == "SELL"
    ]
    positions_out: List[Dict[str, Any]] = []
    for ticker in OPEN_POSITION_TICKERS:
        position = next((row for row in position_rows if str(row.get("ticker") or "").upper() == ticker), {})
        order = _position_order_evidence(order_rows, position) if position else {}
        missing = _missing_position_evidence(position, order) if position else ["local position record"]
        positions_out.append({
            "ticker": ticker,
            "base_size": str(position.get("bot_managed_base") or position.get("position_size_base") or "0"),
            "avg_entry": str(position.get("entry_price") or ""),
            "quote_exposure": str(position.get("position_size_quote") or ""),
            "source_order_id": str(position.get("source_entry_order_id") or position.get("order_id") or ""),
            "exchange_order_id": str(position.get("phase_c43_exchange_order_id") or position.get("order_id") or ""),
            "source_client_order_id": str(position.get("phase_c43_client_order_id") or ""),
            "protective_stop_status": str(position.get("protective_stop_status") or ""),
            "d2_status": str(position.get("d2_plan_status") or position.get("position_plan_status") or ""),
            "d3_status": str(position.get("d3_exit_status") or ""),
            "can_enter_exit_pipeline_now": False,
            "missing_evidence": missing,
            "required_fix": "verify fill/order evidence, current base balance, avg entry, invalidation/stop, D2 plan, D3 preview, and operator ACK before any live exit management",
            "local_order_status": str(order.get("status") or ""),
            "local_order_has_exchange_order_id": bool(str(order.get("exchange_order_id") or order.get("order_id") or "").strip()),
            "open_exit_orders_same_ticker": [
                str(row.get("client_order_id") or "")
                for row in open_exits
                if str(row.get("ticker") or row.get("product_id") or "").upper() == ticker
            ],
        })
    state_integrity_blockers = []
    if open_exits:
        missing_exit_ids = [
            str(row.get("client_order_id") or "")
            for row in open_exits
            if not str(row.get("exchange_order_id") or row.get("order_id") or "").strip()
        ]
        if missing_exit_ids:
            state_integrity_blockers.append({"type": "open_exit_missing_exchange_order_id", "client_order_ids": missing_exit_ids})
    return {
        "generated_at": now_iso(),
        "phase": "open_orders_and_positions_reconciliation_preview_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "open_orders_current": len(open_orders),
        "historical_order_records": len(order_rows),
        "open_positions_current": len(position_rows),
        "positions": positions_out,
        "state_integrity_blockers": state_integrity_blockers,
        "live_action_required_now": False,
        "safety_policy": {
            "open_orders_are_not_positions": True,
            "zero_open_orders_means_no_cancel": True,
            "open_positions_do_not_imply_auto_close": True,
        },
    }


def build_position_risk_completion_report(*, root: str | Path = ".") -> Dict[str, Any]:
    reconciliation = build_reconciliation_report(root=root)
    positions = []
    for row in reconciliation["positions"]:
        missing = list(row.get("missing_evidence") or [])
        positions.append({
            "ticker": row["ticker"],
            "can_be_managed_by_pipeline": False,
            "reason": "protective_stop_status=position_risk_incomplete",
            "protective_stop_status": row.get("protective_stop_status"),
            "base_size": row.get("base_size"),
            "avg_entry": row.get("avg_entry"),
            "quote_exposure": row.get("quote_exposure"),
            "reserved_base": "0",
            "open_exit_orders": row.get("open_exit_orders_same_ticker"),
            "missing_evidence": missing,
            "required_before_pipeline": [
                "verify exchange fill/order evidence",
                "verify current base balance",
                "compute avg entry",
                "compute stop/invalidation",
                "compute D2/D3 exit plan",
                "operator ACK before any live exit",
            ],
            "recommended_action": "prepare_d2_d3_preview",
        })
    return {
        "generated_at": now_iso(),
        "phase": "open_position_risk_completion_preview_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "live_exit_submitted": False,
        "positions": positions,
        "live_action_required_now": False,
        "safety_policy": {
            "preview_only": True,
            "no_blind_pipeline_reentry": True,
            "operator_ack_required_before_live_exit_management": True,
        },
    }


def build_p0_patch_report(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    replay = _load_json(project_root / "reports/audits/live-entry-guard-incident-replay-latest.json")
    runtime = _load_json(project_root / "reports/audits/runtime-guard-version-readiness-latest.json")
    amount = _load_json(project_root / "reports/audits/amount-cap-compliance-audit-latest.json")
    reconciliation = build_reconciliation_report(root=project_root)
    return {
        "generated_at": now_iso(),
        "phase": "p0_live_entry_guard_patch_v1",
        "live_entry_guard_version": LIVE_ENTRY_GUARD_VERSION,
        "product_rule_normalizer_version": PRODUCT_RULE_NORMALIZER_VERSION,
        "live_entry_required_gates": list(LIVE_ENTRY_REQUIRED_GATES),
        "patched_block_reasons": [
            "blocked_wait_decision_cannot_live_submit",
            "blocked_preview_only_cannot_live_submit",
            "blocked_valid_trade_plan_false",
            "blocked_missing_fresh_approve_trade",
            "blocked_missing_product_rules",
            "blocked_precision_invalid",
            "blocked_open_position_same_ticker",
            "blocked_open_order_same_ticker",
        ],
        "p0_replay_blocked": bool(replay.get("all_historical_submitted_incidents_blocked_now")),
        "runtime_proof_prepared": bool(runtime.get("runtime_proof_prepared")),
        "safe_runtime_loaded": bool(runtime.get("safe_runtime_loaded")),
        "amount_cap_violation_found": bool(amount.get("violations")),
        "amount_cap_conclusion": amount.get("conclusion"),
        "open_orders_current": reconciliation.get("open_orders_current"),
        "open_positions_current": reconciliation.get("open_positions_current"),
        "state_integrity_blockers": reconciliation.get("state_integrity_blockers"),
        "live_side_effects": {
            "coinbase_submit": False,
            "coinbase_cancel": False,
            "coinbase_replace": False,
            "state_open_orders_mutation": False,
            "state_positions_mutation": False,
            "service_restart": False,
        },
        "readiness": "p0_fixed_on_disk_pending_tests_and_operator_position_decision",
    }


def _write_json_md(report: Dict[str, Any], *, json_path: Path, md_title: str, rows_key: str = "") -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = json_path.with_suffix(".md")
    lines = [
        f"# {md_title}",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- phase: {report.get('phase')}",
        f"- read_only: {report.get('read_only', True)}",
        f"- coinbase_call_attempted: {report.get('coinbase_call_attempted', False)}",
        f"- state_write_performed: {report.get('state_write_performed', False)}",
    ]
    if "open_orders_current" in report:
        lines.append(f"- open_orders_current: {report.get('open_orders_current')}")
    if "open_positions_current" in report:
        lines.append(f"- open_positions_current: {report.get('open_positions_current')}")
    if rows_key and isinstance(report.get(rows_key), list):
        lines.extend(["", "| ticker | can enter/manage pipeline | reason/status | missing evidence |", "|---|---:|---|---|"])
        for row in report.get(rows_key) or []:
            lines.append(
                f"| {row.get('ticker')} | {row.get('can_enter_exit_pipeline_now', row.get('can_be_managed_by_pipeline'))} | "
                f"{row.get('protective_stop_status', row.get('reason', ''))} | {', '.join(row.get('missing_evidence') or [])} |"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    reconciliation = build_reconciliation_report(root=project_root)
    risk = build_position_risk_completion_report(root=project_root)
    p0 = build_p0_patch_report(root=project_root)
    _write_json_md(
        reconciliation,
        json_path=project_root / "reports/audits/open-orders-and-positions-reconciliation-preview-latest.json",
        md_title="Open Orders And Positions Reconciliation Preview",
        rows_key="positions",
    )
    _write_json_md(
        risk,
        json_path=project_root / "reports/audits/open-position-risk-completion-preview-latest.json",
        md_title="Open Position Risk Completion Preview",
        rows_key="positions",
    )
    _write_json_md(
        p0,
        json_path=project_root / "reports/audits/p0-live-entry-guard-patch-latest.json",
        md_title="P0 Live Entry Guard Patch",
    )
    return {"reconciliation": reconciliation, "risk_completion": risk, "p0_patch": p0}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write P0 live-entry safety preview reports.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    reports = write_reports(root=args.root)
    if args.json:
        print(json.dumps(reports, indent=2, sort_keys=True))
    else:
        print("wrote_p0_live_entry_safety_reports=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "build_reconciliation_report",
    "build_position_risk_completion_report",
    "build_p0_patch_report",
    "write_reports",
    "main",
    "parse_args",
]
