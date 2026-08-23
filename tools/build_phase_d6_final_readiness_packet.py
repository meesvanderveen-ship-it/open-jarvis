#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_final_readiness_packet import build_phase_d6_final_readiness_packet  # noqa: E402
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


def _load_json(path: str) -> Dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _environment_summary() -> Dict[str, object]:
    bwrap_path = shutil.which("bwrap")
    return {
        "bwrap_on_path": bool(bwrap_path),
        "bwrap_path": bwrap_path,
        "system_package_mutation_performed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 final report-only readiness packet. No Coinbase, OpenAI API, live action, or state writes."
    )
    parser.add_argument("--readiness-report", required=True, help="Existing reports/d6 live-test readiness JSON")
    parser.add_argument("--governance-evidence-report", default="", help="Optional reports/d6 governance evidence JSON")
    parser.add_argument("--readiness-index-report", default="", help="Optional reports/d6 readiness index JSON")
    parser.add_argument("--readiness-regression-status", default="", help="Optional selected readiness regression status")
    parser.add_argument("--readiness-regression-tests-passed", type=int, default=0)
    parser.add_argument("--readiness-regression-command", default="")
    parser.add_argument("--output", default="", help="Optional JSON output path under reports/d6/")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown output path under reports/d6/")
    parser.add_argument("--metadata-sidecar", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes_before = _state_hashes()
    source_paths = [
        args.readiness_report,
        "docs/CODEX_PROJECT_ROADMAP.md",
        "docs/FUTURE_LIVE_TEST_PREFLIGHT_TEMPLATE.md",
        "docs/FUTURE_LIVE_TEST_PROMPT_SKELETON.md",
    ]
    governance = _load_json(args.governance_evidence_report) if args.governance_evidence_report else {}
    readiness_index = _load_json(args.readiness_index_report) if args.readiness_index_report else {}
    if args.governance_evidence_report:
        source_paths.append(args.governance_evidence_report)
    if args.readiness_index_report:
        source_paths.append(args.readiness_index_report)
    hashes_after = _state_hashes()
    packet = build_phase_d6_final_readiness_packet(
        readiness_report=_load_json(args.readiness_report),
        governance_evidence_report=governance,
        readiness_index_report=readiness_index,
        regression_summary={
            "status": args.readiness_regression_status,
            "tests_passed": args.readiness_regression_tests_passed,
            "command": args.readiness_regression_command,
        }
        if args.readiness_regression_status
        else {},
        state_hashes_before=hashes_before,
        state_hashes_after=hashes_after,
        environment_summary=_environment_summary(),
        source_report_paths=source_paths,
    )
    report = build_phase_d6_report_bundle(
        report_type="d6_final_readiness_packet",
        content=packet,
        source_paths=source_paths,
        input_hashes=hashes_before,
    )
    if args.output:
        result = write_phase_d6_report_bundle(report, args.output, metadata_sidecar=args.metadata_sidecar)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    if args.markdown_output:
        write_phase_d6_report_bundle(report, args.markdown_output, markdown=True, metadata_sidecar=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
