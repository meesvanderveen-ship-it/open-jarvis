#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_btc_usdc_24h_live_start_decision_pack import (  # noqa: E402
    build_btc_usdc_24h_live_start_decision_pack,
    render_btc_usdc_24h_live_start_decision_pack_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only BTC-USDC 24h live-start decision pack. Does not start live trading.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_btc_usdc_24h_live_start_decision_pack(root=Path(args.root))
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_btc_usdc_24h_live_start_decision_pack_markdown(report)
    if args.json_out:
        _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))
    if args.markdown:
        print(markdown_text, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(json_text, end="")
    else:
        flags = report.get("governance_flags") or {}
        print(
            "btc_usdc_24h_live_start_decision_pack "
            f"classification={report.get('classification')} "
            f"decision_status={report.get('decision_status')} "
            f"ready_for_operator_fresh_preflight={flags.get('ready_for_operator_fresh_preflight')} "
            f"live_start_authorized={flags.get('live_start_authorized')} "
            f"state_write_performed={(report.get('metadata') or {}).get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
