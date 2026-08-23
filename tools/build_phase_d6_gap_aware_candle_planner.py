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

from bot.phase_d6_gap_aware_candle_planner import (  # noqa: E402
    build_backtest_readiness_v13,
    build_gap_aware_candle_planner,
    build_gap_fill_command_plan,
    build_master_packet_v13,
    build_open_source_inspiration_report,
    build_post_gap_fill_quality_summary,
    build_preflight_v3,
    discover_candle_files,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _split_csv(values: List[str] | None) -> List[str]:
    out: List[str] = []
    for value in values or []:
        out.extend(part.strip() for part in str(value).split(",") if part.strip())
    return out


def _write(*, report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 gap-aware candle planner v13 reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--candidate-root", default="/tmp/d6_gap_fill_20260601_v13")
    parser.add_argument("--max-chunks-per-gap", type=int, default=25)
    parser.add_argument("--tickers", action="append", help="Comma-separated or repeatable tickers")
    parser.add_argument("--timeframes", action="append", help="Comma-separated or repeatable timeframes")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tickers = _split_csv(args.tickers)
    timeframes = _split_csv(args.timeframes)
    candle_paths = [
        str(path)
        for path in discover_candle_files(
            tickers=tickers or None,
            timeframes=timeframes or None,
        )
        if path.exists()
    ]
    source_paths = ["bot/config.py", *candle_paths]

    inspiration = build_open_source_inspiration_report()
    planner = build_gap_aware_candle_planner(
        tickers=tickers or None,
        timeframes=timeframes or None,
        candidate_root=args.candidate_root,
        max_chunks_per_gap=args.max_chunks_per_gap,
        as_of=args.as_of,
    )
    command_plan = build_gap_fill_command_plan(planner=planner)
    quality = build_post_gap_fill_quality_summary(candle_paths=candle_paths, as_of=args.as_of)
    backtest = build_backtest_readiness_v13(quality_summary=quality, planner=planner)
    preflight = build_preflight_v3(quality_summary=quality, planner=planner)
    master = build_master_packet_v13(
        open_source_report=inspiration,
        planner=planner,
        command_plan=command_plan,
        quality_summary=quality,
        backtest_readiness=backtest,
        preflight_v3=preflight,
    )

    specs = [
        ("d6_open_source_inspiration_gap_aware_refresh_v1", inspiration, "open-source-inspiration-gap-aware-refresh-v1"),
        ("d6_gap_aware_candle_planner_v1", planner, "gap-aware-candle-planner-v1"),
        ("d6_gap_fill_command_plan_v1", command_plan, "gap-fill-command-plan-v1"),
        ("d6_post_gap_fill_dataset_quality_summary_v13", quality, "post-gap-fill-dataset-quality-summary-v13"),
        ("d6_exploratory_only_backtest_readiness_refresh_v13", backtest, "exploratory-only-backtest-readiness-refresh-v13"),
        ("d6_24h_live_test_preflight_runner_v3", preflight, "24h-live-test-preflight-runner-v3"),
        ("d6_24h_readiness_master_packet_v13", master, "24h-readiness-master-packet-v13"),
    ]
    results = [
        _write(report_type=report_type, content=content, stem=stem, date_stamp=args.date_stamp, source_paths=source_paths)
        for report_type, content, stem in specs
    ]
    if args.json:
        print(json.dumps({"status": "gap_aware_candle_planner_reports_written", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
