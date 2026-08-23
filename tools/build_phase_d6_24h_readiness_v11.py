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

from bot.phase_d6_24h_readiness_v11 import (  # noqa: E402
    build_exploratory_backtest_result_bundle,
    build_preflight_runner_report,
    build_readiness_master_v11,
    build_recent_tail_refresh_plan,
    load_report_content,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


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


def _local_safety() -> Dict[str, Any]:
    open_orders = json.loads(_run(["python3", "tools/show_open_orders.py", "--open-only", "--json", "--limit", "20"]).stdout)
    audit = _run(["python3", "tools/show_function_preservation_audit.py", "--fail-on-review"])
    d3 = json.loads(_run(["python3", "tools/show_phase_d3_controlled_live_exits.py", "--ticker", "BTC-USDC", "--json"]).stdout)
    return {
        "open_orders": open_orders,
        "function_audit_stdout": audit.stdout,
        "d3": d3,
        "state_hashes": _state_hashes(),
    }


def _write(*, report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def _split_csv(raw: str) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 24h readiness v11 research-only reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--coverage-report", default="reports/d6/multi-ticker-dataset-coverage-plan-refresh-v9-20260601.json")
    parser.add_argument("--quality-report", default="reports/d6/post-fetch-dataset-quality-summary-v9-20260601.json")
    parser.add_argument("--readiness-report", default="reports/d6/24h-readiness-master-packet-v10-20260601.json")
    parser.add_argument("--exploratory-tickers", default="BTC-USDC,ETH-USDC,SOL-USDC")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_paths = [args.coverage_report, args.quality_report, args.readiness_report]
    coverage = load_report_content(args.coverage_report)
    quality = load_report_content(args.quality_report)
    readiness = load_report_content(args.readiness_report)
    local_safety = _local_safety()
    tail_plan = build_recent_tail_refresh_plan(coverage_report=coverage, quality_report=quality, as_of=args.as_of)
    exploratory = build_exploratory_backtest_result_bundle(
        coverage_report=coverage,
        quality_report=quality,
        tickers=_split_csv(args.exploratory_tickers),
        as_of=args.as_of,
    )
    preflight = build_preflight_runner_report(
        local_safety=local_safety,
        readiness_report=readiness,
        as_of=args.as_of,
    )
    master = build_readiness_master_v11(
        tail_plan=tail_plan,
        exploratory_bundle=exploratory,
        preflight_report=preflight,
        as_of=args.as_of,
    )
    specs = [
        ("d6_recent_tail_dataset_refresh_plan_v1", tail_plan, "recent-tail-dataset-refresh-plan-v1"),
        ("d6_exploratory_only_backtest_result_bundle_v1", exploratory, "exploratory-only-backtest-result-bundle-v1"),
        ("d6_24h_live_test_preflight_runner_v1", preflight, "24h-live-test-preflight-runner-v1"),
        ("d6_24h_readiness_master_packet_v11", master, "24h-readiness-master-packet-v11"),
    ]
    results = [
        _write(report_type=report_type, content=content, stem=stem, date_stamp=args.date_stamp, source_paths=source_paths)
        for report_type, content, stem in specs
    ]
    payload = {
        "status": "d6_24h_readiness_v11_reports_written",
        "results": results,
        "summary": {
            "tail_fetch_executed": tail_plan["fetch_executed"],
            "exploratory_result_count": exploratory["result_count"],
            "preflight_result": preflight["preflight_result"],
            "all_ticker_24h_status": master["all_ticker_24h_status"],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
