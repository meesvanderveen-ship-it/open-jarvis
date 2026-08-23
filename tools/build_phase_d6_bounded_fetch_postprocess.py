#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_bounded_fetch_postprocess import (  # noqa: E402
    build_bounded_fetch_result_report,
    build_dataset_coverage_refresh,
    build_post_fetch_dataset_quality_summary,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


AS_OF = "2026-06-01T00:00:00Z"


def _run(args: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True)


def _state_hashes() -> Dict[str, str]:
    result = _run(["sha256sum", "state/open_orders.json", "state/positions.json"])
    hashes: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            hashes[parts[1]] = parts[0]
    return hashes


def _candle_paths() -> List[str]:
    root = PROJECT_ROOT / "research_data/coinbase/candles"
    return sorted(str(path.relative_to(PROJECT_ROOT)) for path in root.glob("product=*/timeframe=*/study_window=*.json"))


def _write(
    *,
    report_type: str,
    content: Dict[str, Any],
    stem: str,
    date_stamp: str,
    source_paths: List[str],
    input_hashes: Dict[str, str],
) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(
        report_type=report_type,
        content=content,
        source_paths=source_paths,
        input_hashes=input_hashes,
    )
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build post-fetch D.6 research-only reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candle_paths = _candle_paths()
    state_hashes = _state_hashes()
    config_text = Path("bot/config.py").read_text(encoding="utf-8")
    requested_rows = [
        {
            "ticker": "BTC-USDC",
            "timeframe": "1H",
            "requested_chunks": 2,
            "chunks_fetched": 2,
            "output_path": "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json",
        },
        {
            "ticker": "BTC-USDC",
            "timeframe": "4H",
            "requested_chunks": 2,
            "chunks_fetched": 2,
            "output_path": "research_data/coinbase/candles/product=BTC-USDC/timeframe=4H/study_window=3y.json",
        },
    ]
    sandbox_errors = [
        {"ticker": "BTC-USDC", "timeframe": "1H", "error": "sandbox_dns_failed_before_escalated_fetch"},
        {"ticker": "BTC-USDC", "timeframe": "4H", "error": "sandbox_dns_failed_before_escalated_fetch"},
    ]
    fetch_result = build_bounded_fetch_result_report(
        requested_rows=requested_rows,
        max_chunks=2,
        sandbox_errors=sandbox_errors,
        escalated_fetch_performed=True,
    )
    coverage = build_dataset_coverage_refresh(config_text=config_text, candle_paths=candle_paths, as_of=AS_OF)
    quality = build_post_fetch_dataset_quality_summary(candle_paths=candle_paths, as_of=AS_OF)
    source_paths = [
        "reports/d6/prefetch-validation-report-20260601.json",
        "reports/d6/data-fetch-ack-package-20260601.json",
        "reports/d6/future-multi-ticker-fetch-plan-v2-20260601.json",
        "reports/d6/multi-ticker-dataset-coverage-plan-20260601.json",
        "reports/d6/master-readiness-refresh-v2-20260601.json",
        "reports/d6/next-ack-decision-packet-20260601.json",
        "bot/config.py",
    ] + candle_paths
    specs = [
        ("d6_bounded_multi_ticker_candle_fetch_result", fetch_result, "bounded-multi-ticker-candle-fetch-result"),
        ("d6_multi_ticker_dataset_coverage_plan_refresh", coverage, "multi-ticker-dataset-coverage-plan-refresh"),
        ("d6_post_fetch_dataset_quality_summary", quality, "post-fetch-dataset-quality-summary"),
    ]
    results = [
        _write(
            report_type=report_type,
            content=content,
            stem=stem,
            date_stamp=args.date_stamp,
            source_paths=source_paths,
            input_hashes=state_hashes,
        )
        for report_type, content, stem in specs
    ]
    print(json.dumps({"status": "bounded_fetch_postprocess_reports_written", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
