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

from bot.phase_d6_bounded_coverage_expansion import (  # noqa: E402
    build_coverage_expansion_result,
    build_coverage_refresh_v2,
    build_quality_summary_v2,
    discover_candidate_candle_pairs,
    merge_candidate_candles,
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
    parser = argparse.ArgumentParser(description="Merge bounded candle coverage expansion and write D.6 reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--max-chunks", type=int, required=True)
    parser.add_argument("--public-call-count", type=int, required=True)
    parser.add_argument("--version-label", default="", help="Optional suffix such as v3 for output stems and report names")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_root = Path(args.candidate_root)
    pairs = discover_candidate_candle_pairs(candidate_root=candidate_root)
    merge_results = []
    for pair in pairs:
        merge_results.append(
            {
                "product": pair["product"],
                "timeframe": pair["timeframe"],
                "study_window": pair["study_window"],
                **merge_candidate_candles(existing_path=pair["existing_path"], candidate_path=pair["candidate_path"]),
            }
        )
    candle_paths = _candle_paths()
    state_hashes = _state_hashes()
    config_text = Path("bot/config.py").read_text(encoding="utf-8")
    expansion = build_coverage_expansion_result(
        merge_results=merge_results,
        max_chunks=args.max_chunks,
        public_call_count=args.public_call_count,
    )
    coverage = build_coverage_refresh_v2(config_text=config_text, candle_paths=candle_paths, as_of=AS_OF)
    quality = build_quality_summary_v2(candle_paths=candle_paths, as_of=AS_OF)
    suffix = f"-{args.version_label}" if args.version_label else ""
    if args.version_label:
        expansion["report_name"] = f"bounded_candle_coverage_expansion_result_{args.version_label}"
        expansion["status"] = f"bounded_candle_coverage_expansion_{args.version_label}_ready"
        coverage["report_name"] = f"multi_ticker_dataset_coverage_plan_refresh_{args.version_label}"
        coverage["status"] = f"multi_ticker_dataset_coverage_plan_refresh_{args.version_label}_ready"
        quality["report_name"] = f"post_fetch_dataset_quality_summary_{args.version_label}"
        quality["status"] = f"post_fetch_dataset_quality_summary_{args.version_label}_ready"
    source_paths = [
        "reports/d6/bounded-multi-ticker-candle-fetch-result-20260601.json",
        "reports/d6/multi-ticker-dataset-coverage-plan-refresh-20260601.json",
        "reports/d6/post-fetch-dataset-quality-summary-20260601.json",
        "reports/d6/prefetch-validation-report-20260601.json",
        "bot/config.py",
    ] + candle_paths
    specs = [
        (f"d6_bounded_candle_coverage_expansion_result{suffix}", expansion, f"bounded-candle-coverage-expansion-result{suffix}"),
        (f"d6_multi_ticker_dataset_coverage_plan_refresh{suffix}", coverage, f"multi-ticker-dataset-coverage-plan-refresh{suffix}"),
        (f"d6_post_fetch_dataset_quality_summary{suffix}", quality, f"post-fetch-dataset-quality-summary{suffix}"),
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
    print(json.dumps({"status": "bounded_coverage_expansion_reports_written", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
