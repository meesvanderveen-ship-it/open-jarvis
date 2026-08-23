#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
PHASE = "pre_live_restart_readiness_v1"

REPAIR_STATUS = Path("reports/audits/repair-sprint-status-latest.json")
PIPELINE_HEALTH = Path("reports/audits/full-pipeline-health-latest.json")
CONTROLLED_CLOSE_PREP = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
RISK_RECONSTRUCTION = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
STALE_LOCK_PLAN = Path("reports/audits/stale-lock-operator-plan-latest.json")
STATE_POSITIONS = Path("state/positions.json")
STATE_OPEN_ORDERS = Path("state/open_orders.json")

READINESS_JSON = Path("reports/audits/pre-live-restart-readiness-latest.json")
READINESS_MD = Path("reports/audits/pre-live-restart-readiness-latest.md")

REQUIRED_OPERATOR_ACTIONS = [
    "decide ADA route",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _reason(*, blockers: List[str], risk_blocking: bool, lock_blocking: bool, controlled_close_pending: bool, ada_pending: bool) -> str:
    if blockers and not risk_blocking and not lock_blocking:
        return "current_state_evidence_unavailable"
    if risk_blocking and lock_blocking:
        return "risk_incomplete_positions_and_runtime_lock"
    if risk_blocking:
        return "risk_incomplete_positions"
    if lock_blocking:
        return "runtime_lock_requires_operator_verification"
    if controlled_close_pending or ada_pending:
        return "operator_actions_pending"
    return "ready"


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


def build_pre_live_restart_readiness(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    current = build_pre_live_current_state(root)
    positions_blocking = list(current.get("risk_incomplete_positions") or [])
    positions_to_close = [ticker for ticker in positions_blocking if ticker != "ADA-USDC"]
    positions_to_review = ["ADA-USDC"] if "ADA-USDC" in positions_blocking else []
    lock = current.get("runtime_lock") if isinstance(current.get("runtime_lock"), dict) else {}
    lock_blocking = bool(lock.get("held") or not lock.get("verifiable", False))
    controlled_close_pending = bool(positions_to_close)
    ada_pending = bool(positions_to_review)
    controlled_close_plan_ready = False
    ticker_universe = _ticker_universe_readiness(root)
    ada_review_done = not ada_pending
    risk_blocking = bool(positions_blocking)
    current_blockers = list(current.get("blockers") or [])
    required_actions = list(REQUIRED_OPERATOR_ACTIONS)
    if positions_to_close:
        required_actions.insert(0, "review current risk-incomplete non-ADA positions")
    if lock_blocking:
        required_actions.append("verify active runtime lock on host")
    if not current.get("state_evidence_available"):
        required_actions.append("restore readable current state evidence")
    safe_to_restart = bool(
        not current_blockers
        and not controlled_close_pending
        and ada_review_done
    )

    return {
        "safe_to_restart": safe_to_restart,
        "reason": _reason(
            blockers=current_blockers,
            risk_blocking=risk_blocking,
            lock_blocking=lock_blocking,
            controlled_close_pending=controlled_close_pending,
            ada_pending=ada_pending,
        ),
        "service_active": bool(lock.get("held")),
        "stale_lock_likely": lock_blocking,
        "open_orders": int(current.get("open_orders") or 0),
        "open_positions": len(current.get("open_positions") or []),
        "positions_blocking_restart": positions_blocking,
        "controlled_close_plan_ready": controlled_close_plan_ready,
        "controlled_close_pending": controlled_close_pending,
        "ada_review_done": ada_review_done,
        "normal_workflow_uses_env_ticker_universe": bool(ticker_universe.get("normal_workflow_uses_env_ticker_universe")),
        "hardcoded_incident_ticker_scope_removed_from_normal_workflow": bool(ticker_universe.get("hardcoded_incident_ticker_scope_removed_from_normal_workflow")),
        "controlled_close_scope_isolated": bool(ticker_universe.get("controlled_close_scope_isolated")),
        "ada_review_scope_isolated": bool(ticker_universe.get("ada_review_scope_isolated")),
        "configured_tickers": list(ticker_universe.get("configured_tickers") or []),
        "eligible_tickers": list(ticker_universe.get("eligible_tickers") or []),
        "blocked_tickers": ticker_universe.get("blocked_tickers") if isinstance(ticker_universe.get("blocked_tickers"), dict) else {},
        "ticker_universe_readiness": ticker_universe,
        "required_operator_actions": required_actions,
        "terminal_operator_status": "do_not_run_bot_yet" if not safe_to_restart else "ready_for_operator_restart",
        "current_state": current,
        "historical_reports_are_diagnostic_only": [
            str(REPAIR_STATUS),
            str(PIPELINE_HEALTH),
            str(CONTROLLED_CLOSE_PREP),
            str(RISK_RECONSTRUCTION),
            str(STALE_LOCK_PLAN),
        ],
    }


def write_pre_live_restart_readiness(report: Dict[str, Any], root: Path = PROJECT_ROOT) -> None:
    json_path = root / READINESS_JSON
    md_path = root / READINESS_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = [
        "# Pre-Live Restart Readiness",
        "",
        f"Generated: `{_now_iso()}`",
        "",
        f"- `safe_to_restart`: `{report.get('safe_to_restart')}`",
        f"- `reason`: `{report.get('reason')}`",
        f"- `service_active`: `{report.get('service_active')}`",
        f"- `stale_lock_likely`: `{report.get('stale_lock_likely')}`",
        f"- `open_orders`: `{report.get('open_orders')}`",
        f"- `open_positions`: `{report.get('open_positions')}`",
        f"- `positions_blocking_restart`: `{json.dumps(report.get('positions_blocking_restart') or [])}`",
        f"- `configured_tickers`: `{json.dumps(report.get('configured_tickers') or [])}`",
        f"- `eligible_tickers`: `{json.dumps(report.get('eligible_tickers') or [])}`",
        f"- `blocked_tickers`: `{json.dumps(report.get('blocked_tickers') or {}, sort_keys=True)}`",
        f"- `controlled_close_plan_ready`: `{report.get('controlled_close_plan_ready')}`",
        f"- `ada_review_done`: `{report.get('ada_review_done')}`",
        f"- `terminal_operator_status`: `{report.get('terminal_operator_status')}`",
        "",
        "## Required Operator Actions",
        "",
    ]
    lines.extend(f"- {action}" for action in report.get("required_operator_actions") or [])
    lines.extend(["", "No live action was taken."])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only pre-live restart readiness.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_pre_live_restart_readiness()
    if args.write_report or args.json_out:
        write_pre_live_restart_readiness(report)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"safe_to_restart: {report.get('safe_to_restart')}")
        print(f"reason: {report.get('reason')}")
        print(f"terminal_operator_status: {report.get('terminal_operator_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
