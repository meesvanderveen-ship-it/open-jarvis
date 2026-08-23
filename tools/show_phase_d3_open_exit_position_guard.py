from __future__ import annotations

import argparse
import json

from bot.phase_d3_open_exit_position_guard import build_open_d3_exit_position_guard_report
from bot.state_store import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the D.3 open-exit position close guard report.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--linked-position-id", default="")
    parser.add_argument("--attempted-new-status", default="closed")
    parser.add_argument("--attempted-position-size-base", default="0")
    parser.add_argument("--attempted-bot-managed-base", default="0")
    parser.add_argument("--caller-reason", default="")
    parser.add_argument("--evidence-status", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    state = StateStore()
    current = state.get_position(args.ticker) or {}
    proposed = dict(current)
    proposed.update(
        {
            "ticker": args.ticker,
            "status": args.attempted_new_status,
            "position_size_base": args.attempted_position_size_base,
            "bot_managed_base": args.attempted_bot_managed_base,
        }
    )
    report = build_open_d3_exit_position_guard_report(
        ticker=args.ticker,
        current_position=current,
        proposed_position=proposed,
        linked_position_id=args.linked_position_id,
        caller_reason=args.caller_reason,
        evidence_status=args.evidence_status,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
