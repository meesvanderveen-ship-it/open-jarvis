#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig  # noqa: E402
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path, serialize_report  # noqa: E402
from bot.phase_live_tiny_btc_preflight import (  # noqa: E402
    ACTUAL_SUBMIT_ACK,
    build_btc_usdc_tiny_live_preflight_report,
)


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(safe)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report-only BTC-USDC tiny-budget live preflight. No Coinbase calls and no state writes."
    )
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/")
    parser.add_argument("--actual-submit-ack", default="", help="Exact ACK required before accepting ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true.")
    parser.add_argument(
        "--require-actual-submit-enabled",
        action="store_true",
        help="For the later armed-start preflight only: require actual submit to be enabled and ACKed.",
    )
    parser.add_argument("--print-ack", action="store_true", help="Print the exact actual-submit ACK string and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.print_ack:
        print(ACTUAL_SUBMIT_ACK)
        return 0

    cfg = BotConfig()
    try:
        cfg.validate()
    except Exception as exc:
        report = {
            "phase": "btc_usdc_tiny_live_preflight_v1",
            "status": "blocked_btc_usdc_tiny_preflight",
            "blockers": ["bot_config_validate_failed"],
            "validation_error": str(exc),
            "no_coinbase_call": True,
            "no_live_action": True,
            "state_write_performed": False,
            "env_mutation_performed": False,
        }
    else:
        report = build_btc_usdc_tiny_live_preflight_report(
            cfg,
            actual_submit_ack=args.actual_submit_ack,
            require_actual_submit_enabled=args.require_actual_submit_enabled,
        )

    if args.json_out:
        _atomic_write(Path(args.json_out), json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8") + b"\n")
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), serialize_report(report, markdown=True))

    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0 if report.get("status") == "pass_btc_usdc_tiny_preflight" else 2


if __name__ == "__main__":
    raise SystemExit(main())
