#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE = "ada_position_decision_prep_v1"
TICKER = "ADA-USDC"

CONTROLLED_CLOSE_PREP = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
RISK_RECONSTRUCTION = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
STATE_POSITIONS = Path("state/positions.json")
ADA_DECISION_JSON = Path("reports/audits/ada-position-decision-prep-latest.json")
ADA_DECISION_MD = Path("reports/audits/ada-position-decision-prep-latest.md")

ROUTES = ["manual_hold_review", "risk_completion_apply_after_ack", "controlled_close_after_ack"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_position(report: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    positions = report.get("positions") if isinstance(report.get("positions"), list) else []
    for position in positions:
        if not isinstance(position, dict):
            continue
        if str(position.get("ticker") or "").strip().upper() == ticker:
            return position
    return {}


def build_ada_position_decision(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    prep = _load_json(root, CONTROLLED_CLOSE_PREP)
    risk = _load_json(root, RISK_RECONSTRUCTION)
    state = _load_json(root, STATE_POSITIONS)
    prep_position = _find_position(prep, TICKER)
    risk_position = _find_position(risk, TICKER)
    state_position = state.get(TICKER) if isinstance(state.get(TICKER), dict) else {}

    below_stop = bool(prep_position.get("below_reconstructed_stop"))
    current_status = str(
        state_position.get("protective_stop_status")
        or ("position_risk_incomplete" if state_position.get("position_risk_incomplete") else "")
        or "position_risk_incomplete"
    )
    base_balance_verified = bool(
        prep_position.get("base_balance_verified")
        or risk_position.get("current_base_balance_verified")
    )
    positions_to_close = [str(item).strip().upper() for item in prep.get("positions_to_close") or []]
    return {
        "ticker": TICKER,
        "current_status": current_status,
        "above_reconstructed_stop": not below_stop,
        "base_balance_verified": base_balance_verified,
        "routes": list(ROUTES),
        "recommended_route": "manual_hold_review_or_risk_completion_after_ack",
        "operator_ack_required": True,
        "live_action_allowed_now": False,
        "phase": PHASE,
        "generated_at": _now_iso(),
        "ada_in_controlled_close_batch": TICKER in positions_to_close,
        "controlled_close_batch": positions_to_close,
        "state_write_allowed_now": False,
        "will_not_run_now": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submit_attempted": False,
        "live_order_submitted": False,
        "state_write_performed": False,
        "open_orders_mutated": False,
        "positions_mutated": False,
        "service_restart_attempted": False,
        "lock_removed": False,
    }


def write_ada_position_decision(report: Dict[str, Any], root: Path = PROJECT_ROOT) -> None:
    json_path = root / ADA_DECISION_JSON
    md_path = root / ADA_DECISION_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = [
        "# ADA Position Decision Prep",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"- `ticker`: `{report.get('ticker')}`",
        f"- `current_status`: `{report.get('current_status')}`",
        f"- `above_reconstructed_stop`: `{report.get('above_reconstructed_stop')}`",
        f"- `base_balance_verified`: `{report.get('base_balance_verified')}`",
        f"- `routes`: `{json.dumps(report.get('routes') or [])}`",
        f"- `recommended_route`: `{report.get('recommended_route')}`",
        f"- `operator_ack_required`: `{report.get('operator_ack_required')}`",
        f"- `live_action_allowed_now`: `{report.get('live_action_allowed_now')}`",
        f"- `ada_in_controlled_close_batch`: `{report.get('ada_in_controlled_close_batch')}`",
        "",
        "No live action was taken.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare read-only ADA position decision routes.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_ada_position_decision()
    if args.write_report:
        write_ada_position_decision(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"ticker: {report.get('ticker')}")
        print(f"recommended_route: {report.get('recommended_route')}")
        print(f"live_action_allowed_now: {report.get('live_action_allowed_now')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
