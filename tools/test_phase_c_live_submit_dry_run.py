#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.phase_c_live_submitter import run_phase_c_live_submit_dry_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a Phase-C C.2.1 live-submit dry-run audit. This never submits to Coinbase."
    )
    parser.add_argument("--ticker", default="BTC-USDC", help="Synthetic diagnostic ticker to use")
    parser.add_argument(
        "--simulate-ready-guard",
        action="store_true",
        help="Use a copied in-memory config with Phase-C guard inputs enabled; actual Coinbase submit remains disabled.",
    )
    parser.add_argument(
        "--audit-path",
        default=str(PROJECT_ROOT / "logs" / "phase_c_live_submit.jsonl"),
        help="Audit JSONL path to append the diagnostic record to",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    result = run_phase_c_live_submit_dry_run(
        cfg=cfg,
        ticker=args.ticker,
        audit_path=args.audit_path,
        simulate_ready_guard=args.simulate_ready_guard,
        append_audit=True,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("Phase-C C.2.1 live-submit dry-run audit")
        print("========================================")
        print("ticker:", result.get("ticker"))
        print("status:", result.get("status"))
        print("diagnostic:", result.get("diagnostic"))
        print("dry_run:", result.get("dry_run"))
        print("simulate_ready_guard:", result.get("simulate_ready_guard"))
        print("guard_allows_live_submit:", (result.get("guard_result_full") or {}).get("guard_allows_live_submit"))
        print("hard_block_reasons:", json.dumps(result.get("hard_block_reasons") or [], sort_keys=True))
        print("payload_accepted:", (result.get("payload") or {}).get("accepted"))
        print("client_order_id:", (result.get("payload") or {}).get("client_order_id"))
        print("live_submission_attempted:", result.get("live_submission_attempted"))
        print("live_order_submitted:", result.get("live_order_submitted"))
        print("audit_path:", args.audit_path)
        print("Safety: diagnostic dry-run only; no Coinbase client is provided and submit_live is false.")

    if result.get("live_submission_attempted") or result.get("live_order_submitted"):
        print("ERROR: dry-run attempted/submitted a live order", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
