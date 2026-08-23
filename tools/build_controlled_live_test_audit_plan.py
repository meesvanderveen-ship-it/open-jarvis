#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_controlled_live_test_audit_plan import build_controlled_live_test_audit_plan  # noqa: E402
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


def _load_optional_json(path: str) -> Dict[str, object]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report-only controlled live-test readiness audit and one-day run plan. No Coinbase calls."
    )
    parser.add_argument("--final-readiness-packet", default="reports/d6/final-readiness-packet-20260601.json")
    parser.add_argument("--live-readiness-report", default="reports/d6/live-test-readiness-20260601.json")
    parser.add_argument("--governance-evidence-report", default="reports/d6/governance-evidence-bundle-20260601.json")
    parser.add_argument("--coverage-manifest", action="append", default=["reports/d6/coverage/btc-usdc-1d-3y-sample-manifest.json"])
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--output", default="", help="Optional JSON output path under reports/d6/")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown output path under reports/d6/")
    parser.add_argument("--metadata-sidecar", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes_before = _state_hashes()
    coverage_paths = _split_csv(args.coverage_manifest)
    source_paths = [
        "bot/config.py",
        args.order_events,
        args.final_readiness_packet,
        args.live_readiness_report,
        args.governance_evidence_report,
        *coverage_paths,
        "docs/FUTURE_LIVE_TEST_PROMPT_SKELETON.md",
    ]
    hashes_after = _state_hashes()
    plan = build_controlled_live_test_audit_plan(
        config_text=Path("bot/config.py").read_text(encoding="utf-8"),
        order_events_path=args.order_events,
        coverage_manifest_paths=coverage_paths,
        final_readiness_packet=_load_optional_json(args.final_readiness_packet),
        live_readiness_report=_load_optional_json(args.live_readiness_report),
        governance_evidence_report=_load_optional_json(args.governance_evidence_report),
        state_hashes_before=hashes_before,
        state_hashes_after=hashes_after,
    )
    report = build_phase_d6_report_bundle(
        report_type="d6_controlled_live_test_audit_plan",
        content=plan,
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
