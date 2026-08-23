#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_24h_readiness_sprint import (  # noqa: E402
    build_24h_preflight_architecture,
    build_24h_readiness_master_v10,
    build_dataset_quality_warning_diagnostic,
    build_exploratory_backtest_readiness,
    load_report_content,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _write(*, report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(
        report_type=report_type,
        content=content,
        source_paths=source_paths,
    )
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 24h readiness research-only sprint reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--coverage-report", default="reports/d6/multi-ticker-dataset-coverage-plan-refresh-v9-20260601.json")
    parser.add_argument("--quality-report", default="reports/d6/post-fetch-dataset-quality-summary-v9-20260601.json")
    parser.add_argument("--readiness-report", default="reports/d6/24h-readiness-bundle-v9-20260601.json")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_paths = [args.coverage_report, args.quality_report, args.readiness_report]
    coverage = load_report_content(args.coverage_report)
    quality = load_report_content(args.quality_report)
    readiness = load_report_content(args.readiness_report)
    warning_diagnostic = build_dataset_quality_warning_diagnostic(quality_report=quality, as_of=args.as_of)
    exploratory = build_exploratory_backtest_readiness(
        coverage_report=coverage,
        quality_report=quality,
        as_of=args.as_of,
    )
    preflight = build_24h_preflight_architecture(
        coverage_report=coverage,
        quality_report=quality,
        readiness_report=readiness,
        as_of=args.as_of,
    )
    master = build_24h_readiness_master_v10(
        warning_diagnostic=warning_diagnostic,
        exploratory_readiness=exploratory,
        preflight_architecture=preflight,
        as_of=args.as_of,
    )
    specs = [
        ("d6_dataset_quality_warning_diagnostic_v1", warning_diagnostic, "dataset-quality-warning-diagnostic-v1"),
        ("d6_exploratory_only_backtest_readiness_v1", exploratory, "exploratory-only-backtest-readiness-v1"),
        ("d6_24h_live_test_preflight_architecture_v1", preflight, "24h-live-test-preflight-architecture-v1"),
        ("d6_24h_readiness_master_packet_v10", master, "24h-readiness-master-packet-v10"),
    ]
    results = [
        _write(
            report_type=report_type,
            content=content,
            stem=stem,
            date_stamp=args.date_stamp,
            source_paths=source_paths,
        )
        for report_type, content, stem in specs
    ]
    payload = {
        "status": "d6_24h_readiness_sprint_reports_written",
        "results": results,
        "summary": {
            "quality_warning_counts": warning_diagnostic["warning_counts"],
            "exploratory_only_command_count": exploratory["exploratory_only_command_count"],
            "btc_usdc_only_24h_status": master["btc_usdc_only_24h_status"],
            "all_ticker_24h_status": master["all_ticker_24h_status"],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
