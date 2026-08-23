#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_all_ticker_live_readonly_preflight import (  # noqa: E402
    CoinbaseReadonlyProductBalanceAdapter,
    build_all_ticker_live_readonly_preflight,
    collect_all_ticker_live_readonly_snapshot,
    render_all_ticker_live_readonly_preflight_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _write(path: Path, text: str) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, safe)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build all-ticker live-readonly preflight report. Default mode does not call Coinbase."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument(
        "--allow-coinbase-readonly",
        action="store_true",
        help="Explicitly allow bounded Coinbase readonly product/balance checks. No orders endpoints are called.",
    )
    args = parser.parse_args()

    live_readonly_snapshot = None
    if args.allow_coinbase_readonly:
        from bot.coinbase_client import CoinbaseClient  # noqa: E402

        readonly_client = CoinbaseReadonlyProductBalanceAdapter(CoinbaseClient())
        live_readonly_snapshot = collect_all_ticker_live_readonly_snapshot(readonly_client)

    report = build_all_ticker_live_readonly_preflight(
        root=args.root,
        live_readonly_snapshot=live_readonly_snapshot,
    )
    js = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    md = render_all_ticker_live_readonly_preflight_markdown(report)
    if args.json_out:
        _write(Path(args.json_out), js)
    if args.markdown_out:
        _write(Path(args.markdown_out), md)
    if args.markdown:
        print(md, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(js, end="")
    else:
        gate = report.get("gate_decision") or {}
        print(
            "all_ticker_live_readonly_preflight "
            f"attempted={gate.get('all_ticker_live_readonly_preflight_attempted')} "
            f"passed={gate.get('all_ticker_live_readonly_preflight_passed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
