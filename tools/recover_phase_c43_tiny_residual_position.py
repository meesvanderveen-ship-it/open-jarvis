from __future__ import annotations

import argparse
import json

from bot.config import BotConfig
from bot.coinbase_client import CoinbaseClient
from bot.order_store import OrderStore
from bot.phase_c43_tiny_residual_recovery import (
    TARGET_CLIENT_ORDER_ID,
    TARGET_POSITION_ID,
    TARGET_TICKER,
    build_phase_c43_tiny_residual_recovery_report,
)
from bot.state_store import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or controlled apply for one specific Phase-C43 tiny-residual pilot position recovery."
    )
    parser.add_argument("--ticker", default=TARGET_TICKER)
    parser.add_argument("--position-id", default=TARGET_POSITION_ID)
    parser.add_argument("--client-order-id", "--expected-client-order-id", dest="client_order_id", default=TARGET_CLIENT_ORDER_ID)
    parser.add_argument("--expected-live-base", required=True)
    parser.add_argument("--live-base-tolerance", default="0.0000000001")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-ack", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("use either --dry-run or --apply")
    if not args.apply:
        args.dry_run = True

    cfg = BotConfig()
    cfg.validate()

    report = build_phase_c43_tiny_residual_recovery_report(
        ticker=args.ticker,
        position_id=args.position_id,
        client_order_id=args.client_order_id,
        expected_live_base=args.expected_live_base,
        live_base_tolerance=args.live_base_tolerance,
        apply=args.apply,
        apply_ack=args.apply_ack,
        state_store=StateStore(),
        order_store=OrderStore(),
        coinbase_client=CoinbaseClient(),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Phase-C43 tiny residual recovery")
        print("status:", report.get("status"))
        print("dry_run:", report.get("dry_run"))
        print("blockers:", report.get("blockers"))
        print("proposed_changes:")
        for key, diff in (report.get("proposed_changes") or {}).items():
            print(f"  - {key}: {diff.get('before')} -> {diff.get('after')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
