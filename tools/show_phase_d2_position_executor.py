#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.phase_d2_position_executor import build_phase_d2_position_executor_report
from bot.state_store import StateStore


def _sample_position(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "status": "open",
        "order_id": f"sample-d2-{ticker}",
        "entry_price": "100.00",
        "position_size_base": "0.25",
        "position_size_quote": "25.00",
        "entry_reason": "sample_position_for_d2_preview",
        "stop_price": "97.50",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Phase D.2 position-executor / bracket-lite status")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sample-position", action="store_true", help="Gebruik een synthetische positie-preview als er nog geen live/open positie is")
    parser.add_argument("--persist-plan", action="store_true", help="Sla plan alleen op als het ready is; geen live SELL-submit")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    position = _sample_position(args.ticker) if args.sample_position else None
    report = build_phase_d2_position_executor_report(
        cfg=cfg,
        ticker=args.ticker,
        state_store=StateStore(),
        position=position,
        persist_plan=args.persist_plan,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    plan = report.get("plan") or {}
    edge = ((plan.get("fee_edge") or {}) if isinstance(plan, dict) else {})
    print("Phase D.2 position executor + multi-exit bracket-lite + fee-aware edge")
    print("====================================================================")
    print(f"status: {report.get('status')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"open_position_count: {report.get('open_position_count')}")
    print(f"ignored_position_count: {report.get('ignored_position_count')}")
    print(f"selected_position_present: {report.get('selected_position_present')}")
    print(f"raw_selected_position_present: {report.get('raw_selected_position_present')}")
    print(f"plan_ready_no_live_exit_submit: {report.get('plan_ready_no_live_exit_submit', False)}")
    print(f"live_sell_submit_attempted_by_this_tool: {report.get('live_sell_submit_attempted_by_this_tool')}")
    print(f"live_sell_order_submitted: {report.get('live_sell_order_submitted')}")
    print()
    print(f"Blockers: {json.dumps(report.get('blockers', []))}")
    print(f"Warnings: {json.dumps(report.get('warnings', []))}")
    if plan:
        print("Entry:", json.dumps(plan.get("entry", {}), sort_keys=True))
        print("Risk:", json.dumps(plan.get("risk", {}), sort_keys=True))
        print("Exits:", json.dumps(plan.get("exits", []), sort_keys=True))
        print("Fee/net edge:", json.dumps({
            "status": edge.get("status"),
            "expected_gross_profit_pct": edge.get("expected_gross_profit_pct"),
            "estimated_total_cost_pct": (edge.get("cost_model") or {}).get("estimated_total_cost_pct"),
            "expected_net_edge_pct": edge.get("expected_net_edge_pct"),
            "reward_to_fee_ratio": edge.get("reward_to_fee_ratio"),
            "reward_to_risk_ratio": edge.get("reward_to_risk_ratio"),
        }, sort_keys=True))
    print()
    print("Safety: D.2 maakt alleen position-executor plannen en exit-intenties. Geen live SELL-submit; D.3 is nodig voor controlled reduce-only exits.")
    print("D.2.1 hygiene: ghost/zero-base en TEST-* diagnostic positions worden genegeerd voor D.3-voorbereiding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
