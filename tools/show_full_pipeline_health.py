#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from bot.config import BotConfig
from bot.env_ticker_universe import (
    build_env_ticker_universe_workflow_readiness,
    load_product_rules_for_readiness,
)
from bot.pre_live_current_state import build_pre_live_current_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE = "full_pipeline_health_v1"
REPAIR_STATUS = Path("reports/audits/repair-sprint-status-latest.json")
CONTROLLED_CLOSE_PREP = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
RISK_RECONSTRUCTION = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
OPERATOR_DECISION = Path("reports/audits/position-risk-operator-decision-latest.json")
ENTRY_AUDIT = Path("reports/audits/entry-order-type-and-orderbook-usage-audit-latest.json")
STATE_POSITIONS = Path("state/positions.json")
STATE_OPEN_ORDERS = Path("state/open_orders.json")
PIPELINE_HEALTH_JSON = Path("reports/audits/full-pipeline-health-latest.json")
PIPELINE_HEALTH_MD = Path("reports/audits/full-pipeline-health-latest.md")
OPERATOR_CHECKLIST = [
    "[ ] controlled close ETH/AVAX/SOL uitgevoerd of bewust afgewezen",
    "[ ] ADA route gekozen",
    "[ ] stale lock handmatig geverifieerd en verwijderd",
    "[ ] pre-live restart readiness groen",
    "[ ] runtime guard version opnieuw geladen na restart",
    "[ ] eerste full cycle post-restart gecontroleerd",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        data = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _state_open_positions(root: Path) -> List[str]:
    state = _load_json(root, STATE_POSITIONS)
    out: List[str] = []
    for ticker, position in state.items():
        if not isinstance(position, dict):
            continue
        if str(position.get("status") or "open").strip().lower() in {"open", "active"}:
            out.append(str(ticker).strip().upper())
    return sorted(out)


def _state_risk_incomplete_positions(root: Path) -> List[str]:
    state = _load_json(root, STATE_POSITIONS)
    out: List[str] = []
    for ticker, position in state.items():
        if not isinstance(position, dict):
            continue
        if str(position.get("status") or "open").strip().lower() not in {"open", "active"}:
            continue
        stop = str(position.get("stop_price") or "").strip()
        invalidation = str(position.get("invalidation_price") or "").strip()
        incomplete = (
            bool(position.get("position_risk_incomplete"))
            or str(position.get("protective_stop_status") or "").strip().lower() == "position_risk_incomplete"
            or stop in {"", "0", "0.0", "0.00"}
            or invalidation in {"", "0", "0.0", "0.00"}
        )
        if incomplete:
            out.append(str(ticker).strip().upper())
    return sorted(out)


def _state_open_order_count(root: Path) -> int:
    state = _load_json(root, STATE_OPEN_ORDERS)
    orders = state.get("orders") if isinstance(state.get("orders"), dict) else {}
    count = 0
    for order in orders.values():
        if not isinstance(order, dict):
            continue
        if str(order.get("status") or "").strip().lower() in {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending", "open", "active", "new", "queued"}:
            count += 1
    return count


def _market_order_flags_enabled() -> List[str]:
    return [
        name
        for name in ("MARKET_ORDER_ENABLED", "ENABLE_MARKET_ORDERS", "ALLOW_MARKET_ORDERS")
        if os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
    ]


def _ticker_universe_readiness(root: Path) -> Dict[str, Any]:
    try:
        cfg = BotConfig()
        return build_env_ticker_universe_workflow_readiness(
            cfg=cfg,
            product_rules_by_ticker=load_product_rules_for_readiness(root),
        )
    except Exception as exc:
        return {
            "normal_workflow_uses_env_ticker_universe": False,
            "hardcoded_incident_ticker_scope_removed_from_normal_workflow": False,
            "controlled_close_scope_isolated": True,
            "ada_review_scope_isolated": True,
            "configured_tickers": [],
            "eligible_tickers": [],
            "blocked_tickers": {"__config__": [f"config_unavailable:{type(exc).__name__}"]},
            "read_only": True,
            "coinbase_call_attempted": False,
            "state_write_performed": False,
        }


def build_full_pipeline_health_report(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    current = build_pre_live_current_state(root)
    repair = _load_json(root, REPAIR_STATUS)
    close = _load_json(root, CONTROLLED_CLOSE_PREP)
    risk = _load_json(root, RISK_RECONSTRUCTION)
    decision = _load_json(root, OPERATOR_DECISION)
    entry = _load_json(root, ENTRY_AUDIT)
    risk_summary = risk.get("summary") if isinstance(risk.get("summary"), dict) else {}
    entry_summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    ticker_universe = _ticker_universe_readiness(root)
    state_open_positions = list(current.get("open_positions") or [])
    risk_incomplete_positions = list(current.get("risk_incomplete_positions") or [])
    positions_to_close = [ticker for ticker in risk_incomplete_positions if ticker != "ADA-USDC"]
    positions_to_review = ["ADA-USDC"] if "ADA-USDC" in risk_incomplete_positions else []
    position_risk_done = not risk_incomplete_positions
    blockers: List[str] = list(current.get("blockers") or [])
    enabled_market_flags = _market_order_flags_enabled()
    if enabled_market_flags:
        blockers.append("market_order_flags_enabled_forbidden_orderbook_workflow")
    if positions_to_close:
        blockers.append("controlled_close_not_executed")
    if positions_to_review:
        blockers.append("ada_review_not_completed")
    blockers = sorted(set(blockers))
    safe_to_restart = not blockers
    entry_contract = "pass" if entry_summary.get("current_guard_blocks_replay") is True else "fail"
    fill_contract = (
        "pass"
        if risk_summary.get("all_local_positions_match_fill_evidence") is True
        and risk_summary.get("all_entry_fills_proven_post_only_limit_maker") is True
        else "unknown"
    )
    exit_contract = (
        "pass"
        if position_risk_done
        else "blocked_by_position_risk_incomplete"
    )
    health = "green" if not blockers and safe_to_restart else "red"
    return {
        "phase": PHASE,
        "generated_at": _now_iso(),
        "pipeline_health": health,
        "safe_to_restart": safe_to_restart,
        "service_active": bool((current.get("runtime_lock") or {}).get("held")),
        "stale_lock_likely": bool((current.get("runtime_lock") or {}).get("held") or not (current.get("runtime_lock") or {}).get("verifiable", False)),
        "open_orders": int(current.get("open_orders") or 0),
        "open_positions": len(state_open_positions),
        "entry_pipeline_contract": entry_contract,
        "fill_to_position_contract": fill_contract,
        "exit_pipeline_contract": exit_contract,
        "controlled_close_plan_ready": False,
        "positions_to_close": positions_to_close,
        "positions_to_review": positions_to_review,
        "positions_risk_incomplete": risk_incomplete_positions,
        "ack_required": "",
        "operator_action": "decide ADA route" if positions_to_review else "request explicit service-start ACK",
        "repair_status_operator_action": str(repair.get("next_operator_action") or ""),
        "prior_operator_action": str(decision.get("operator_action") or ""),
        "operator_checklist": list(OPERATOR_CHECKLIST),
        "normal_workflow_uses_env_ticker_universe": bool(ticker_universe.get("normal_workflow_uses_env_ticker_universe")),
        "hardcoded_incident_ticker_scope_removed_from_normal_workflow": bool(ticker_universe.get("hardcoded_incident_ticker_scope_removed_from_normal_workflow")),
        "controlled_close_scope_isolated": bool(ticker_universe.get("controlled_close_scope_isolated")),
        "ada_review_scope_isolated": bool(ticker_universe.get("ada_review_scope_isolated")),
        "configured_tickers": list(ticker_universe.get("configured_tickers") or []),
        "eligible_tickers": list(ticker_universe.get("eligible_tickers") or []),
        "blocked_tickers": ticker_universe.get("blocked_tickers") if isinstance(ticker_universe.get("blocked_tickers"), dict) else {},
        "ticker_universe_readiness": ticker_universe,
        "do_not_run_bot_yet": not safe_to_restart,
        "terminal_operator_status": "do_not_run_bot_yet" if not safe_to_restart else "ready_for_operator_start_ack",
        "blockers": blockers,
        "market_order_flags_enabled": enabled_market_flags,
        "current_state": current,
        "source_reports_diagnostic_only": [
            str(REPAIR_STATUS),
            str(CONTROLLED_CLOSE_PREP),
            str(RISK_RECONSTRUCTION),
            str(OPERATOR_DECISION),
            str(ENTRY_AUDIT),
        ],
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "lock_removed": False,
        "service_restart_attempted": False,
    }


def write_full_pipeline_health_report(report: Dict[str, Any], root: Path = PROJECT_ROOT) -> None:
    json_path = root / PIPELINE_HEALTH_JSON
    md_path = root / PIPELINE_HEALTH_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    md = [
        "# Full Pipeline Health",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"- `pipeline_health`: `{report.get('pipeline_health')}`",
        f"- `safe_to_restart`: `{report.get('safe_to_restart')}`",
        f"- `service_active`: `{report.get('service_active')}`",
        f"- `stale_lock_likely`: `{report.get('stale_lock_likely')}`",
        f"- `open_orders`: `{report.get('open_orders')}`",
        f"- `open_positions`: `{report.get('open_positions')}`",
        f"- `entry_pipeline_contract`: `{report.get('entry_pipeline_contract')}`",
        f"- `fill_to_position_contract`: `{report.get('fill_to_position_contract')}`",
        f"- `exit_pipeline_contract`: `{report.get('exit_pipeline_contract')}`",
        f"- `configured_tickers`: `{json.dumps(report.get('configured_tickers') or [])}`",
        f"- `eligible_tickers`: `{json.dumps(report.get('eligible_tickers') or [])}`",
        f"- `blocked_tickers`: `{json.dumps(report.get('blocked_tickers') or {}, sort_keys=True)}`",
        f"- `controlled_close_plan_ready`: `{report.get('controlled_close_plan_ready')}`",
        f"- `operator_action`: `{report.get('operator_action')}`",
        f"- `terminal_operator_status`: `{report.get('terminal_operator_status')}`",
        "",
        f"Blockers: `{json.dumps(report.get('blockers') or [])}`",
        "",
        "## Operator Checklist",
        "",
        *(str(item) for item in report.get("operator_checklist") or []),
        "",
        "No live action was taken.",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only full pipeline health from existing audit reports.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_full_pipeline_health_report()
    if args.write_report or args.json_out:
        write_full_pipeline_health_report(report)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"pipeline_health: {report.get('pipeline_health')}")
        print(f"safe_to_restart: {report.get('safe_to_restart')}")
        print(f"operator_action: {report.get('operator_action')}")
        print(f"terminal_operator_status: {report.get('terminal_operator_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
