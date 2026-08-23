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

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402
from bot.phase_per_ticker_product_rule_evidence_cache import (  # noqa: E402
    build_per_ticker_product_rule_evidence_cache_report,
    render_per_ticker_product_rule_evidence_cache_markdown,
)


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build local/report-only per-ticker product-rule evidence cache. No Coinbase calls, no HTTP calls, "
            "no market-data fetch, no parameter mutation and no trading-state writes."
        )
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT), help="Project root; defaults to this repository.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_per_ticker_product_rule_evidence_cache_report(root=Path(args.root))
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_per_ticker_product_rule_evidence_cache_markdown(report)

    if args.json_out:
        _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(json_text, end="")
    else:
        gate = report.get("gate_decision") or {}
        print(
            "per_ticker_product_rule_evidence_cache "
            f"classification={report.get('classification')} "
            f"ready={gate.get('per_ticker_product_rule_evidence_cache_ready')} "
            f"all_ticker_product_rule_evidence_ready={gate.get('all_ticker_product_rule_evidence_ready')} "
            f"tickers_ready_count={gate.get('tickers_ready_count')} "
            f"tickers_missing_count={gate.get('tickers_missing_count')} "
            f"state_write_performed={(report.get('metadata') or {}).get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
