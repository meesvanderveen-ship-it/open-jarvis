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

from bot.full_bot_near_miss_phase_c_review import (  # noqa: E402
    build_full_bot_near_miss_phase_c_review_report,
    load_json_file,
    render_full_bot_near_miss_phase_c_review_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build preview-only near-miss to Phase-C fresh review report.")
    parser.add_argument("--adapter-report", required=True, help="Full Bot maker BUY live adapter JSON report.")
    parser.add_argument("--fresh-review-evidence", default="", help="Optional JSON evidence file with fresh judge/risk output. No approval is invented when omitted.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", default="", help="Optional JSON output path under reports/d6/.")
    parser.add_argument("--markdown-out", default="", help="Optional Markdown output path under reports/d6/.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    adapter_path = Path(args.adapter_report)
    evidence_path = Path(args.fresh_review_evidence) if args.fresh_review_evidence else None
    adapter_report = load_json_file(adapter_path)
    evidence = load_json_file(evidence_path) if evidence_path else None
    source_paths = [adapter_path] + ([evidence_path] if evidence_path else [])
    report = build_full_bot_near_miss_phase_c_review_report(
        adapter_report=adapter_report,
        fresh_review_evidence=evidence,
        source_paths=source_paths,
    )

    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_bot_near_miss_phase_c_review_markdown(report)
    if args.json_out:
        _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json or not (args.json_out or args.markdown_out):
        print(json_text, end="")
    else:
        print(
            "full_bot_near_miss_phase_c_review "
            f"status={report.get('status')} "
            f"classification={report.get('classification')} "
            f"review_only={report.get('review_only')} "
            f"selected={len(report.get('selected_candidates') or [])} "
            f"promoted={len(report.get('promoted_phase_c_ready_candidates') or [])} "
            f"phase_c_all_passed={(report.get('phase_c_guard_after_review') or {}).get('all_phase_c_guards_passed')} "
            f"live_order_submit_attempted={report.get('live_order_submit_attempted')} "
            f"coinbase_write_attempted={report.get('coinbase_write_attempted')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
