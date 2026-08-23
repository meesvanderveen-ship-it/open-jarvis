#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_backlearning_data_contracts_v12 import build_backlearning_data_contracts_v12  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


def _content(path: str) -> dict:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(loaded.get("content") or loaded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build D.6 backlearning data contracts v12.")
    parser.add_argument("--quality", required=True)
    parser.add_argument("--known-gap", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = build_backlearning_data_contracts_v12(quality_summary=_content(args.quality), known_gap_decision=_content(args.known_gap))
    bundle = build_phase_d6_report_bundle(report_type="backlearning_data_contracts_v12", content=report, source_paths=[args.quality, args.known_gap])
    write_phase_d6_report_bundle(bundle, args.report, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, Path(args.report).with_suffix(".md"), markdown=True)
    print(json.dumps({"status": report["status"], "report": args.report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
