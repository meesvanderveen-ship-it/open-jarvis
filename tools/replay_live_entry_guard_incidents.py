#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness


TARGET_INCIDENTS = [
    {"ticker": "ETH-USDC", "timestamp": "2026-06-17T12:05:32.759697Z"},
    {"ticker": "AVAX-USDC", "timestamp": "2026-06-17T16:09:26.761466Z"},
    {"ticker": "SOL-USDC", "timestamp": "2026-06-17T20:06:33.471448Z"},
    {"ticker": "ADA-USDC", "timestamp": "2026-06-18T04:06:27.028667Z"},
]
BLOCK_REASON_PRIORITY = [
    "blocked_wait_decision_cannot_live_submit",
    "blocked_preview_only_cannot_live_submit",
    "blocked_valid_trade_plan_false",
    "blocked_missing_fresh_approve_trade",
    "blocked_missing_product_rules",
    "blocked_precision_invalid",
    "blocked_open_position_same_ticker",
    "blocked_open_order_same_ticker",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _nested_dict(value: Any, *keys: str) -> Dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _cfg_from_historical(row: Dict[str, Any], ticker: str) -> SimpleNamespace:
    guard = _nested_dict(row, "guard_result") or _nested_dict(row, "guard_snapshot")
    cfg = dict(guard.get("config") or {})
    defaults = {
        "enable_phase_c_live_small_limit_orders": True,
        "execution_mode": "live",
        "enable_limit_order_manager": True,
        "enable_live_limit_orders": True,
        "enable_live_entry_orders": True,
        "enable_live_exit_orders": False,
        "phase_c_allowed_tickers": [ticker],
        "phase_c_max_order_quote": "100.00",
        "min_live_order_quote_usdc": "20.00",
        "max_live_order_quote_usdc": "100.00",
        "phase_c_max_open_entry_orders": 3,
        "phase_c_max_new_orders_per_cycle": 1,
        "phase_c_max_cancels_per_cycle": 2,
        "phase_c_max_replaces_per_cycle": 1,
        "phase_c_require_pending_intent": True,
        "phase_c_require_promotion_ready": True,
        "phase_c_require_fresh_judge": True,
        "phase_c_require_risk_approval": True,
        "phase_c_require_orderbook_freshness": True,
        "phase_c_entry_order_min_expiry_minutes": 15,
        "phase_c_entry_order_default_expiry_minutes": 60,
        "phase_c_entry_order_max_expiry_hours": 6,
        "phase_c_disable_exit_limit_orders": False,
        "phase_c_paper_shadow_log": True,
        "enable_phase_c_live_submit_infrastructure": True,
        "enable_phase_c_actual_coinbase_submit": True,
        "phase_c_live_order_post_only": True,
        "enable_orderbook_entry_planner": True,
        "enable_resting_limit_entry_preview": True,
        "enable_resting_limit_entry_live_submit": True,
        "enable_pending_entry_lifecycle": True,
        "autonomous_max_order_quote": "100.00",
        "max_notional_usd": "100.00",
        "enable_bounded_exploration_mode": False,
    }
    defaults.update(cfg)
    if ticker not in [str(x).upper() for x in defaults.get("phase_c_allowed_tickers", [])]:
        defaults["phase_c_allowed_tickers"] = list(defaults.get("phase_c_allowed_tickers") or []) + [ticker]
    return SimpleNamespace(**defaults)


def _candidate_from_historical(row: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    risk = _nested_dict(row, "risk_snapshot")
    old_guard = _nested_dict(row, "guard_result") or _nested_dict(row, "guard_snapshot")
    old_summary = _nested_dict(old_guard, "candidate_summary")
    submit_payload = _nested_dict(row, "submit_result", "payload") or _nested_dict(row, "payload")
    preview = _nested_dict(risk, "orderbook_entry_preview")
    product_rules = (
        risk.get("product_rules")
        or _nested_dict(submit_payload, "product_rules")
        or _nested_dict(submit_payload, "product_rules_used")
        or _nested_dict(preview, "product_rules")
    )
    quote = _first_text(
        risk.get("quote_size"),
        submit_payload.get("size_quote_requested"),
        submit_payload.get("size_quote_normalized"),
        preview.get("quote_size"),
        "20.00",
    )
    limit_price = _first_text(
        risk.get("limit_price"),
        submit_payload.get("limit_price"),
        submit_payload.get("limit_price_normalized"),
        preview.get("entry_level"),
        "1",
    )
    decision = _first_text(old_summary.get("judge_decision"), _nested_dict(risk, "fresh_judge_live_buy_approval").get("decision"), "wait").lower()
    judge_side = _first_text(old_summary.get("judge_side"), _nested_dict(risk, "fresh_judge_live_buy_approval").get("side"), "NONE").upper()
    valid_trade_plan = bool(_nested_dict(risk, "fresh_judge_live_buy_approval").get("valid_trade_plan"))
    plan_action = _first_text(old_summary.get("plan_action"), preview.get("recommended_entry_type"), risk.get("entry_route_type"), "prepare_resting_limit_entry")
    trigger_ready = bool(old_summary.get("pending_intent_trigger_ready"))
    orderbook_summary = {
        "snapshot_available": True,
        "freshness_status": _first_text(old_summary.get("orderbook_freshness_status"), "fresh"),
        "spread_pct": _first_text(preview.get("spread_pct"), "0.001"),
    }
    analysis = {
        "ticker": ticker,
        "judge": {
            "decision": decision,
            "side": judge_side,
            "size_quote": quote if decision == "approve_trade" else "0",
            "valid_trade_plan": valid_trade_plan,
            "judge_response_valid_trade_plan": valid_trade_plan,
        },
        "trade_plan": {
            "valid_trade_plan": valid_trade_plan,
            "plan_action": plan_action,
            "side": "BUY",
            "entry_zone_low": preview.get("entry_level"),
            "entry_zone_high": preview.get("entry_level"),
            "preferred_limit_price": limit_price,
            "invalidation_price": preview.get("invalidation_level") or "0.99",
            "stop_loss": preview.get("invalidation_level") or "0.99",
            "take_profit_1": (preview.get("target_levels") or ["1.10"])[0] if isinstance(preview.get("target_levels"), list) else "1.10",
            "max_quote_size": quote,
            "trigger": "historical resting-entry replay",
        },
        "feature_pack": {
            "market": {
                "best_bid": preview.get("best_bid"),
                "best_ask": preview.get("best_ask"),
                "mid_price": preview.get("current_mid"),
                "spread_pct": preview.get("spread_pct"),
            },
            "orderbook_context": {
                "snapshot_available": True,
                "best_bid": preview.get("best_bid"),
                "best_ask": preview.get("best_ask"),
                "mid_price": preview.get("current_mid"),
            },
            "decision_context": {
                "product_rules": product_rules,
                "pending_order_intent": {
                    "status": old_summary.get("pending_intent_status") or "waiting",
                    "trigger_ready": trigger_ready,
                    "requires_fresh_judge_and_risk": True,
                },
            },
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "plan_action": plan_action,
        "prepare_resting_limit_entry": True,
        "trigger_ready": trigger_ready,
        "read_only": True,
        "orderbook_summary": orderbook_summary,
    }
    order_intent = {
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": plan_action,
        "prepare_resting_limit_entry": True,
        "trigger_ready": trigger_ready,
        "size_quote": quote,
        "limit_price": limit_price,
        "intent_id": f"historical-replay-{ticker}",
        "product_rules": product_rules,
    }
    live_risk = {"accepted": True, "approved": True, "risk_approved": True, "mode": "live_phase_c_replay"}
    return {
        "analysis": analysis,
        "execution_plan": execution_plan,
        "order_intent": order_intent,
        "live_risk_result": live_risk,
        "product_rules": product_rules if isinstance(product_rules, dict) else {},
    }


def _incident_id(ticker: str, timestamp: str) -> str:
    return f"{ticker}:{timestamp}"


def _select_block_reason(reasons: Sequence[str]) -> str:
    for reason in BLOCK_REASON_PRIORITY:
        if reason in reasons:
            return reason
    return reasons[0] if reasons else ""


def replay_incidents(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    rows = load_jsonl(project_root / "logs/phase_c_live_submit.jsonl")
    results: List[Dict[str, Any]] = []
    for target in TARGET_INCIDENTS:
        ticker = target["ticker"]
        timestamp = target["timestamp"]
        matching = [
            row for row in rows
            if str(row.get("generated_at") or "").replace("+00:00", "Z").startswith(timestamp.rstrip("Z"))
            and str(row.get("ticker") or "").upper() == ticker
        ]
        row = matching[-1] if matching else {}
        candidate = _candidate_from_historical(row, ticker) if row else {}
        if row:
            guard = evaluate_phase_c_live_entry_readiness(
                cfg=_cfg_from_historical(row, ticker),
                ticker=ticker,
                analysis=candidate["analysis"],
                execution_plan=candidate["execution_plan"],
                order_intent=candidate["order_intent"],
                live_risk_result=candidate["live_risk_result"],
                open_live_entry_orders_count=0,
                open_live_entry_order_tickers=[],
                open_positions=[],
                new_live_orders_this_cycle=0,
                product_rules=candidate["product_rules"],
            )
            reasons = list(guard.get("hard_block_reasons") or [])
            would_submit = bool(guard.get("guard_allows_live_submit"))
            current_result = "would_submit" if would_submit else "blocked"
            block_reason = "" if would_submit else _select_block_reason(reasons)
        else:
            guard = {}
            reasons = ["historical_incident_record_not_found"]
            would_submit = False
            current_result = "missing_evidence"
            block_reason = "historical_incident_record_not_found"
        results.append({
            "incident_id": _incident_id(ticker, timestamp),
            "timestamp": timestamp,
            "ticker": ticker,
            "historical_live_submitted": bool(row.get("live_order_submitted")) if row else False,
            "current_guard_result": current_result,
            "block_reason": block_reason,
            "hard_block_reasons": reasons,
            "would_submit_now": would_submit,
            "guard_summary": {
                "live_entry_guard_version": guard.get("live_entry_guard_version"),
                "candidate_summary": guard.get("candidate_summary"),
            },
        })
    return {
        "generated_at": now_iso(),
        "phase": "live_entry_guard_incident_replay_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "incidents_replayed": len(results),
        "all_historical_submitted_incidents_blocked_now": all(
            r["historical_live_submitted"] and r["current_guard_result"] == "blocked" and not r["would_submit_now"]
            for r in results
        ),
        "results": results,
    }


def write_reports(report: Dict[str, Any], *, root: str | Path = ".") -> None:
    project_root = Path(root)
    out_json = project_root / "reports/audits/live-entry-guard-incident-replay-latest.json"
    out_md = project_root / "reports/audits/live-entry-guard-incident-replay-latest.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Live Entry Guard Incident Replay",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- all_blocked_now: {report.get('all_historical_submitted_incidents_blocked_now')}",
        f"- coinbase_call_attempted: {report.get('coinbase_call_attempted')}",
        "",
        "| ticker | historical timestamp | current result | block reason | would submit now |",
        "|---|---:|---|---|---:|",
    ]
    for row in report.get("results") or []:
        lines.append(
            f"| {row.get('ticker')} | {row.get('timestamp')} | {row.get('current_guard_result')} | "
            f"{row.get('block_reason')} | {row.get('would_submit_now')} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay historical wait/resting live-submit incidents against the current guard.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = replay_incidents(root=args.root)
    if not args.no_write:
        write_reports(report, root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"all_blocked_now={report['all_historical_submitted_incidents_blocked_now']}")
    return 0 if report["all_historical_submitted_incidents_blocked_now"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["TARGET_INCIDENTS", "replay_incidents", "write_reports", "main", "parse_args"]
