#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.cleanup_diagnostic_paper_orders import is_diagnostic_order, iter_orders, load_json_state

OPEN_STATUSES = {"active", "planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending", "trigger_ready", "needs_fresh_analysis", "waiting", "stale"}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except Exception:
        return []
    return rows


def safe_config_summary() -> Dict[str, Any]:
    try:
        from bot.config import BotConfig

        cfg = BotConfig()
        cfg.validate()
        return {
            "config_ok": True,
            "execution_mode": cfg.execution_mode,
            "enable_read_only_execution_planner": cfg.enable_read_only_execution_planner,
            "execution_planner_call_on_wait": cfg.execution_planner_call_on_wait,
            "enable_limit_order_manager": cfg.enable_limit_order_manager,
            "enable_live_limit_orders": cfg.enable_live_limit_orders,
            "enable_live_entry_orders": cfg.enable_live_entry_orders,
            "enable_live_exit_orders": cfg.enable_live_exit_orders,
            "enable_paper_no_fill_followup_analysis": getattr(cfg, "enable_paper_no_fill_followup_analysis", None),
            "enable_paper_reserved_balance_checks": getattr(cfg, "enable_paper_reserved_balance_checks", None),
            "enable_paper_order_budget_enforcement": getattr(cfg, "enable_paper_order_budget_enforcement", None),
            "enable_paper_pending_order_intents": getattr(cfg, "enable_paper_pending_order_intents", None),
            "enable_paper_watchlist_intents_from_gate_watch": getattr(cfg, "enable_paper_watchlist_intents_from_gate_watch", None),
            "max_open_paper_orders_total": getattr(cfg, "max_open_paper_orders_total", None),
            "max_open_paper_entry_orders_per_ticker": getattr(cfg, "max_open_paper_entry_orders_per_ticker", None),
            "max_open_paper_exit_orders_per_ticker": getattr(cfg, "max_open_paper_exit_orders_per_ticker", None),
            "paper_pending_intent_ttl_hours": getattr(cfg, "paper_pending_intent_ttl_hours", None),
            "paper_pending_intent_max_records": getattr(cfg, "paper_pending_intent_max_records", None),
            "paper_pending_intent_min_gate_confidence": getattr(cfg, "paper_pending_intent_min_gate_confidence", None),
            "paper_pending_intent_mark_needs_fresh_analysis_status": getattr(cfg, "paper_pending_intent_mark_needs_fresh_analysis_status", None),
            "paper_pending_intent_max_replaced_per_ticker": getattr(cfg, "paper_pending_intent_max_replaced_per_ticker", None),
            "paper_pending_intent_final_retention_hours": getattr(cfg, "paper_pending_intent_final_retention_hours", None),
            "paper_pending_intent_dedupe_tolerance_pct": str(getattr(cfg, "paper_pending_intent_dedupe_tolerance_pct", "")),
            "paper_pending_intent_enable_dedupe_refresh": getattr(cfg, "paper_pending_intent_enable_dedupe_refresh", None),
        }
    except Exception as exc:
        return {"config_ok": False, "config_error": str(exc)}


def record_collection_summary(path: Path, root_key: str, *, open_statuses: set[str]) -> Dict[str, Any]:
    data = load_json_state(path, root_key)
    items_obj = data.get(root_key, {})
    by_status: Dict[str, int] = {}
    by_active_status: Dict[str, int] = {}
    replaced_by_ticker: Dict[str, int] = {}
    open_by_ticker: Dict[str, Dict[str, int]] = {}
    diagnostic_count = 0
    total = 0
    active_total = 0
    trigger_ready: List[str] = []
    needs_fresh_analysis: List[str] = []
    promotion_ready: List[str] = []
    for _key, item in iter_orders(items_obj):
        total += 1
        status = str(item.get("status") or "unknown").lower()
        side = str(item.get("side") or "").upper()
        ticker = str(item.get("ticker") or "UNKNOWN").upper()
        by_status[status] = by_status.get(status, 0) + 1
        if status == "replaced":
            replaced_by_ticker[ticker] = replaced_by_ticker.get(ticker, 0) + 1
        if is_diagnostic_order(item):
            diagnostic_count += 1
        if status in open_statuses:
            active_total += 1
            by_active_status[status] = by_active_status.get(status, 0) + 1
            bucket = open_by_ticker.setdefault(ticker, {"total": 0, "buy": 0, "sell": 0})
            bucket["total"] += 1
            if side == "BUY":
                bucket["buy"] += 1
            elif side == "SELL":
                bucket["sell"] += 1
        if status in open_statuses and status == "trigger_ready":
            trigger_ready.append(ticker)
            promotion_ready.append(ticker)
        elif status in open_statuses and status == "needs_fresh_analysis":
            needs_fresh_analysis.append(ticker)
            promotion_ready.append(ticker)
    base = {
        "path": str(path),
        "by_status": by_status,
        "by_active_status": by_active_status,
        "replaced_by_ticker": replaced_by_ticker,
        "open_by_ticker": open_by_ticker,
        "trigger_ready": trigger_ready,
        "needs_fresh_analysis": needs_fresh_analysis,
        "promotion_ready": promotion_ready,
    }
    if root_key == "orders":
        base.update({"total_orders": total, "open_orders": active_total, "diagnostic_order_count": diagnostic_count})
    else:
        base.update({"total_intents": total, "active_intents": active_total, "diagnostic_intent_count": diagnostic_count})
    return base


def latest_outcome_counts(path: Path, *, limit: int = 200) -> Dict[str, Any]:
    rows = load_jsonl(path)
    sample = rows[-limit:]
    by_label: Dict[str, int] = {}
    diagnostics = 0
    for row in sample:
        label = str(row.get("primary_label") or row.get("label") or "unknown")
        by_label[label] = by_label.get(label, 0) + 1
        ticker = str(row.get("ticker") or "")
        reason = str(row.get("paper_order_reason") or row.get("reason") or "")
        source = str(row.get("source") or "")
        if ticker.startswith("TEST-") or "paper-diagnostic" in reason or reason.startswith("phase_b") or source.startswith("paper_diagnostic"):
            diagnostics += 1
    return {"path": str(path), "rows_total": len(rows), "sample_size": len(sample), "by_label_sample": by_label, "diagnostic_rows_in_sample": diagnostics}


def execution_plan_summary(path: Path, *, limit: int = 200) -> Dict[str, Any]:
    rows = load_jsonl(path)
    sample = rows[-limit:]
    by_action: Dict[str, int] = {}
    for row in sample:
        action = str(row.get("execution_action") or row.get("action") or "unknown")
        by_action[action] = by_action.get(action, 0) + 1
    return {"path": str(path), "rows_total": len(rows), "sample_size": len(sample), "by_action_sample": by_action}


def build_status(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = safe_config_summary()
    orders = record_collection_summary(Path(args.open_orders_path), "orders", open_statuses=OPEN_STATUSES)
    pending = record_collection_summary(Path(args.pending_intents_path), "intents", open_statuses=OPEN_STATUSES)
    outcomes = latest_outcome_counts(Path(args.execution_outcomes_path), limit=args.limit)
    plans = execution_plan_summary(Path(args.execution_plans_path), limit=args.limit)
    warnings: List[str] = []
    if cfg.get("config_ok") and (cfg.get("enable_live_limit_orders") or cfg.get("enable_live_entry_orders") or cfg.get("enable_live_exit_orders")):
        warnings.append("Live limit-order flags staan aan. Voor fase B hoort dit false te zijn.")
    if orders.get("diagnostic_order_count", 0) > 0:
        warnings.append("Diagnostic/test paper-orders aanwezig in open_orders.json; ruim op voor normale runtime.")
    if pending.get("diagnostic_intent_count", 0) > 0:
        warnings.append("Diagnostic/test pending intents aanwezig; ruim op voor normale runtime.")
    if outcomes.get("diagnostic_rows_in_sample", 0) > 0:
        warnings.append("Execution outcome sample bevat diagnostic/testrecords; gebruik --exclude-diagnostics in analyse-tools.")
    if cfg.get("config_ok") and not cfg.get("enable_limit_order_manager"):
        warnings.append("ENABLE_LIMIT_ORDER_MANAGER staat uit; paper manager maakt dan geen paper-orders.")
    if cfg.get("config_ok") and cfg.get("execution_planner_call_on_wait"):
        warnings.append("EXECUTION_PLANNER_CALL_ON_WAIT staat aan; dit kan GPT-kosten verhogen.")
    return {"config": cfg, "orders": orders, "pending_order_intents": pending, "execution_plans": plans, "execution_outcomes": outcomes, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon één compact statusoverzicht voor fase B paper ordermanager.")
    parser.add_argument("--open-orders-path", default="state/open_orders.json")
    parser.add_argument("--pending-intents-path", default="state/pending_order_intents.json")
    parser.add_argument("--execution-outcomes-path", default="logs/execution_outcomes.jsonl")
    parser.add_argument("--execution-plans-path", default="logs/execution_plans.jsonl")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    status = build_status(args)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print("Phase-B paper ordermanager status")
    print("=" * 42)
    cfg = status["config"]
    print(f"config_ok: {cfg.get('config_ok')}")
    if not cfg.get("config_ok"):
        print(f"config_error: {cfg.get('config_error')}")
    else:
        print(f"execution_mode: {cfg.get('execution_mode')}")
        print(f"read_only_execution_planner: {cfg.get('enable_read_only_execution_planner')}")
        print(f"execution_planner_call_on_wait: {cfg.get('execution_planner_call_on_wait')}")
        print(f"limit_order_manager: {cfg.get('enable_limit_order_manager')}")
        print(f"live_limit_orders: {cfg.get('enable_live_limit_orders')}")
        print(f"live_entry_orders: {cfg.get('enable_live_entry_orders')}")
        print(f"live_exit_orders: {cfg.get('enable_live_exit_orders')}")
        print(f"paper_no_fill_followup: {cfg.get('enable_paper_no_fill_followup_analysis')}")
        print(f"paper_reserved_balance_checks: {cfg.get('enable_paper_reserved_balance_checks')}")
        print(f"paper_order_budget_enforcement: {cfg.get('enable_paper_order_budget_enforcement')}")
        print(f"paper_pending_order_intents: {cfg.get('enable_paper_pending_order_intents')}")
        print(f"paper_watchlist_intents_from_gate_watch: {cfg.get('enable_paper_watchlist_intents_from_gate_watch')}")
    print()
    orders = status["orders"]
    print("Orders")
    print(f"total: {orders.get('total_orders')} | open: {orders.get('open_orders')} | diagnostics: {orders.get('diagnostic_order_count')}")
    print("by_status:", json.dumps(orders.get("by_status", {}), ensure_ascii=False, sort_keys=True))
    print("open_by_ticker:", json.dumps(orders.get("open_by_ticker", {}), ensure_ascii=False, sort_keys=True))
    print()
    pending = status["pending_order_intents"]
    print("Pending order-intents")
    print(f"total: {pending.get('total_intents')} | open/active_intents: {pending.get('active_intents')} | diagnostics: {pending.get('diagnostic_intent_count')}")
    print("by_status:", json.dumps(pending.get("by_status", {}), ensure_ascii=False, sort_keys=True))
    print("trigger_ready_current:", json.dumps(pending.get("trigger_ready", []), ensure_ascii=False, sort_keys=True))
    print("needs_fresh_analysis_current:", json.dumps(pending.get("needs_fresh_analysis", []), ensure_ascii=False, sort_keys=True))
    print("promotion_ready_current:", json.dumps(pending.get("promotion_ready", []), ensure_ascii=False, sort_keys=True))
    if pending.get("by_active_status"):
        print("by_active_status:", json.dumps(pending.get("by_active_status", {}), ensure_ascii=False, sort_keys=True))
    if pending.get("replaced_by_ticker"):
        print("replaced_by_ticker:", json.dumps(pending.get("replaced_by_ticker", {}), ensure_ascii=False, sort_keys=True))
    if pending.get("retention"):
        print("retention:", json.dumps(pending.get("retention", {}), ensure_ascii=False, sort_keys=True))
    print()
    plans = status["execution_plans"]
    print("Execution plans")
    print(f"rows_total: {plans.get('rows_total')} | sample: {plans.get('sample_size')}")
    print("by_action_sample:", json.dumps(plans.get("by_action_sample", {}), ensure_ascii=False, sort_keys=True))
    print()
    outcomes = status["execution_outcomes"]
    print("Execution outcomes")
    print(f"rows_total: {outcomes.get('rows_total')} | sample: {outcomes.get('sample_size')} | diagnostics_in_sample: {outcomes.get('diagnostic_rows_in_sample')}")
    print("by_label_sample:", json.dumps(outcomes.get("by_label_sample", {}), ensure_ascii=False, sort_keys=True))
    print()
    if status["warnings"]:
        print("Waarschuwingen")
        for warning in status["warnings"]:
            print(f"- {warning}")
    else:
        print("Waarschuwingen: geen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
