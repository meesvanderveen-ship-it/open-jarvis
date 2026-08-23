from __future__ import annotations

import argparse
import json

from bot.order_store import OrderStore
from bot.phase_d3_rejected_submit_cleanup import build_phase_d3_rejected_submit_cleanup_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark one rejected D.3 ghost submit as a final rejected local record.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-log", default="logs/order_events.jsonl")
    args = parser.parse_args()

    apply = bool(args.apply)
    if not apply:
        args.dry_run = True

    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        linked_position_id=args.linked_position_id,
        reason=args.reason,
        order_store=OrderStore(path=args.order_store, log_path=args.order_log),
        apply=apply,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
