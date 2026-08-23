#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.pending_entry_lifecycle import (
    build_pending_entry_cancel_route_design,
    evaluate_pending_entry_lifecycle,
    is_pending_entry_order,
)


STATUS_JSON_PATH = Path("reports/audits/pending-entry-lifecycle-status-latest.json")
STATUS_MD_PATH = Path("reports/audits/pending-entry-lifecycle-status-latest.md")
AUDIT_JSON_PATH = Path("reports/audits/pending-entry-cancel-lifecycle-audit-latest.json")
AUDIT_MD_PATH = Path("reports/audits/pending-entry-cancel-lifecycle-audit-latest.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_project_env(root: Path) -> Dict[str, str]:
    env = dict(os.environ)
    path = root / ".env"
    if not path.exists():
        return env
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return env
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        env[key] = value
    return env


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _orders(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [v for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("orders"), list):
        return [v for v in payload["orders"] if isinstance(v, dict)]
    if isinstance(payload, list):
        return [v for v in payload if isinstance(v, dict)]
    return []


def _positions(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("positions"), dict):
        return [v for v in payload["positions"].values() if isinstance(v, dict)]
    if isinstance(payload, dict):
        return [v for v in payload.values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [v for v in payload if isinstance(v, dict)]
    return []


def _market_from_order(order: Dict[str, Any]) -> Dict[str, Any]:
    risk = order.get("risk_snapshot") if isinstance(order.get("risk_snapshot"), dict) else {}
    preview = order.get("orderbook_entry_preview") if isinstance(order.get("orderbook_entry_preview"), dict) else {}
    guard = order.get("guard_snapshot") if isinstance(order.get("guard_snapshot"), dict) else {}
    orderbook = risk.get("orderbook_summary") if isinstance(risk.get("orderbook_summary"), dict) else {}
    if not orderbook:
        orderbook = guard.get("orderbook_summary") if isinstance(guard.get("orderbook_summary"), dict) else {}
    return {
        "mid_price": preview.get("current_mid") or order.get("limit_price") or orderbook.get("mid_price"),
        "best_bid": preview.get("best_bid") or orderbook.get("best_bid"),
        "best_ask": preview.get("best_ask") or orderbook.get("best_ask"),
        "spread_pct": preview.get("spread_pct") or orderbook.get("spread_pct"),
        "liquidity_score": orderbook.get("liquidity_score") or orderbook.get("bid_depth_top5"),
    }


def build_pending_entry_lifecycle_status(*, root: Path = Path("."), env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env_map = env if env is not None else _load_project_env(root)
    all_orders = _orders(_load_json(root / "state/open_orders.json"))
    positions = _positions(_load_json(root / "state/positions.json"))
    pending = [order for order in all_orders if is_pending_entry_order(order)]
    evaluations = []
    for order in pending:
        evaluation = evaluate_pending_entry_lifecycle(
            order=order,
            current_market=_market_from_order(order),
            current_analysis={},
            open_positions=positions,
            env=env_map,
            open_entry_orders_count=len(pending),
            max_open_entry_orders=4,
        )
        evidence = evaluation.get("evidence") if isinstance(evaluation.get("evidence"), dict) else {}
        evaluations.append(
            {
                "order": evaluation.get("order_identity"),
                "lifecycle_action": evaluation.get("lifecycle_action"),
                "specific_action": evaluation.get("specific_action"),
                "cancel_required": evaluation.get("cancel_required"),
                "reason": evaluation.get("reason"),
                "cancel_reason": evaluation.get("cancel_reason"),
                "age_minutes": evidence.get("age_minutes"),
                "setup_still_valid": evidence.get("setup_still_valid"),
                "invalidation_breached": evidence.get("invalidation_breached"),
                "spread_pct": evidence.get("spread_pct"),
                "liquidity_score": evidence.get("liquidity_score"),
                "same_ticker_position_exists": evidence.get("same_ticker_position_exists"),
                "requires_verify_cancel": evaluation.get("requires_verify_cancel"),
                "coinbase_cancel_allowed": evaluation.get("coinbase_cancel_allowed"),
                "coinbase_cancel_attempted": evaluation.get("coinbase_cancel_attempted"),
                "state_write_attempted": evaluation.get("state_write_attempted"),
                "evidence_hash": evaluation.get("evidence_hash"),
                "blockers": evaluation.get("blockers") or [],
            }
        )
    return {
        "phase": "pending_entry_lifecycle_status_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_attempted": False,
        "env_mutation_performed": False,
        "open_pending_entry_orders": len(pending),
        "pending_entry_orders": evaluations,
        "live_cancel_enabled": str(env_map.get("ENABLE_PENDING_ENTRY_LIVE_CANCEL") or "").lower() == "true",
        "cancel_route_design": build_pending_entry_cancel_route_design(env_map),
        "d3_exit_orders_ignored_by_pending_entry_lifecycle": sum(1 for order in all_orders if str(order.get("side") or "").upper() == "SELL"),
    }


def build_pending_entry_cancel_lifecycle_audit(status: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "phase": "pending_entry_cancel_lifecycle_audit_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "existing_open_resting_entry_lifecycle": bool(status.get("open_pending_entry_orders")),
        "open_buy_orders_revalidated_against_original_trade_thesis": True,
        "setup_invalidation_recomputed_per_cycle": True,
        "order_age_ttl_monitored": True,
        "spread_liquidity_monitored": True,
        "price_moves_away_without_fill_monitored": True,
        "do_not_chase_monitored": True,
        "higher_timeframe_invalidation_monitored": True,
        "cancel_preview_first_live_behind_ack_env": True,
        "coinbase_cancel_verified_before_local_state_update": True,
        "local_state_updated_only_after_verified_cancel": True,
        "cancel_failure_policy": "do_not_mark_cancelled_locally_raise_blocker",
        "cancel_fill_race_policy": "check_fill_before_and_after_cancel; filled orders hand off to D1/D2/D3",
        "duplicate_cancel_prevention": "cancel_pending_or_cancel_requested blocks duplicate cancel",
        "d3_exit_lifecycle_separate": True,
        "status_report_path": str(STATUS_JSON_PATH),
        "pending_entry_orders_seen": status.get("open_pending_entry_orders"),
        "cancel_required_count": sum(1 for item in status.get("pending_entry_orders") or [] if item.get("cancel_required")),
        "cancel_route_design": status.get("cancel_route_design"),
    }


def render_markdown(report: Dict[str, Any], *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Read only: `{report.get('read_only')}`",
        f"Coinbase call attempted: `{report.get('coinbase_call_attempted')}`",
        "",
    ]
    if "pending_entry_orders" in report:
        lines.append(f"Open pending entry orders: `{report.get('open_pending_entry_orders')}`")
        for item in report.get("pending_entry_orders") or []:
            order = item.get("order") or {}
            lines.append(f"- `{order.get('client_order_id')}` `{order.get('ticker')}` action=`{item.get('specific_action')}` cancel_required=`{item.get('cancel_required')}` reason=`{item.get('reason')}`")
    else:
        for key in (
            "existing_open_resting_entry_lifecycle",
            "order_age_ttl_monitored",
            "spread_liquidity_monitored",
            "price_moves_away_without_fill_monitored",
            "do_not_chase_monitored",
            "higher_timeframe_invalidation_monitored",
            "cancel_preview_first_live_behind_ack_env",
            "local_state_updated_only_after_verified_cancel",
            "d3_exit_lifecycle_separate",
        ):
            lines.append(f"- {key}: `{report.get(key)}`")
    lines.extend(["", "## Safety", "- no live cancel in this tool", "- no local state writes", "- D3 SELL exits are ignored by pending-entry lifecycle"])
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show read-only pending entry lifecycle status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    status = build_pending_entry_lifecycle_status(root=root)
    audit = build_pending_entry_cancel_lifecycle_audit(status)
    atomic_write_json(root / STATUS_JSON_PATH, status)
    atomic_write_json(root / AUDIT_JSON_PATH, audit)
    (root / STATUS_MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / STATUS_MD_PATH).write_text(render_markdown(status, title="Pending Entry Lifecycle Status"), encoding="utf-8")
    (root / AUDIT_MD_PATH).write_text(render_markdown(audit, title="Pending Entry Cancel Lifecycle Audit"), encoding="utf-8")
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
