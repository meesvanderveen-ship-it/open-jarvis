#!/usr/bin/env python3
"""Read-only / ACK-gated local reconciliation for ETH, AVAX and SOL closes.

This command has no order submit, cancel or replace path.  ``--mode check`` is
the default and never changes local state.  ``--mode apply`` only changes local
state after the exact acknowledgement and explicit confirmation flag.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.atomic_io import atomic_write_json
from bot.controlled_position_close_reconciliation import (
    JOURNAL_DEFAULT,
    OPEN_ORDERS_DEFAULT,
    POSITIONS_DEFAULT,
    REQUIRED_CONFIRMATION_FLAG,
    SOURCE_REPORT_DEFAULT,
    reconcile_controlled_position_closes,
)


def _build_read_only_coinbase_client() -> tuple[Optional[Any], dict[str, str]]:
    """Load the existing credential context without changing the .env file."""
    try:
        # The project config loader is the established way to read its existing
        # dotenv context. It does not mutate the file.
        import bot.config  # noqa: F401
        from bot.coinbase_client import CoinbaseClient

        return CoinbaseClient(), {}
    except Exception as exc:
        return None, {"coinbase_client_error_type": type(exc).__name__, "coinbase_client_error": str(exc)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only check or exact-ACK local reconciliation for the filled ETH/AVAX/SOL controlled closes."
    )
    parser.add_argument("--mode", choices=["check", "apply"], default="check")
    parser.add_argument("--ack", default="")
    parser.add_argument(REQUIRED_CONFIRMATION_FLAG, action="store_true")
    parser.add_argument("--source-report", default=str(SOURCE_REPORT_DEFAULT))
    parser.add_argument("--positions-path", default=str(POSITIONS_DEFAULT))
    parser.add_argument("--open-orders-path", default=str(OPEN_ORDERS_DEFAULT))
    parser.add_argument("--journal-path", default=str(JOURNAL_DEFAULT))
    parser.add_argument(
        "--json-out",
        default="reports/live_runs/controlled-position-close-reconciliation-latest.json",
        help="Report destination; this is not bot state.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client, client_error = _build_read_only_coinbase_client()
    report = reconcile_controlled_position_closes(
        mode=args.mode,
        ack=args.ack,
        confirmation=bool(args.i_understand_this_updates_local_filled_close_state),
        coinbase_client=client,
        source_report_path=args.source_report,
        positions_path=args.positions_path,
        open_orders_path=args.open_orders_path,
        journal_path=args.journal_path,
    )
    report.update(client_error)
    report["json_out"] = str(args.json_out)
    report["command_preview"] = {
        "mode": args.mode,
        "coinbase_operations_allowed": ["get_order", "get_recent_fills_for_order"],
        "coinbase_operations_forbidden": ["submit", "cancel", "replace"],
        "apply_requires_exact_ack": True,
        "apply_requires_extra_confirmation": True,
    }
    out = Path(args.json_out)
    atomic_write_json(out, report, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("status") in {
        "controlled_close_reconciliation_check_ready",
        "controlled_close_reconciliation_apply_performed",
        "already_reconciled_noop",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
