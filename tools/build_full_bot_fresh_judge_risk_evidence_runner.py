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

from bot.full_bot_failure_determination_matrix import load_json_file  # noqa: E402
from bot.full_bot_fresh_judge_risk_evidence_runner import (  # noqa: E402
    build_full_bot_fresh_judge_risk_evidence_report,
    load_latest_inputs,
    render_full_bot_fresh_judge_risk_evidence_markdown,
)
from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


def _atomic_write(path: Path, data: bytes) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = safe.with_name(f".{safe.name}.tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build report-only fresh judge/risk evidence packets for full-bot maker BUY candidates."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--d6-report", default="")
    parser.add_argument("--workflow-audit-report", default="")
    parser.add_argument("--failure-matrix-report", default="")
    parser.add_argument("--adapter-report", default="")
    parser.add_argument("--near-miss-review-report", default="")
    parser.add_argument("--orchestrator-report", default="")
    parser.add_argument("--fresh-review-evidence", default="", help="Optional real fresh judge/risk evidence JSON. Omit to require review.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown report.")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    return parser.parse_args(argv)


def _override(payloads: dict, paths: list[Path], key: str, raw: str) -> None:
    if not raw:
        return
    path = Path(raw)
    payloads[key] = load_json_file(path)
    paths.append(path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    payloads, source_paths = load_latest_inputs(root)
    _override(payloads, source_paths, "d6_report", args.d6_report)
    _override(payloads, source_paths, "workflow_audit_report", args.workflow_audit_report)
    _override(payloads, source_paths, "failure_matrix_report", args.failure_matrix_report)
    _override(payloads, source_paths, "adapter_report", args.adapter_report)
    _override(payloads, source_paths, "near_miss_review_report", args.near_miss_review_report)
    _override(payloads, source_paths, "orchestrator_report", args.orchestrator_report)
    evidence = None
    if args.fresh_review_evidence:
        evidence_path = Path(args.fresh_review_evidence)
        evidence = load_json_file(evidence_path)
        source_paths.append(evidence_path)

    report = build_full_bot_fresh_judge_risk_evidence_report(
        root=root,
        fresh_review_evidence=evidence,
        source_paths=source_paths,
        **payloads,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_full_bot_fresh_judge_risk_evidence_markdown(report)
    _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json:
        print(json_text, end="")
    else:
        print(
            "full_bot_fresh_judge_risk_evidence "
            f"classification={report.get('classification')} "
            f"candidates={report.get('candidate_count')} "
            f"fresh_judge_approvals={len(report.get('fresh_judge_approvals') or [])} "
            f"deterministic_live_risk_approvals={len(report.get('deterministic_live_risk_approvals') or [])} "
            f"phase_c_ready={len(report.get('phase_c_ready_candidates_after_evidence') or [])} "
            f"live_order_submit_attempted={report.get('live_order_submit_attempted')} "
            f"coinbase_write_attempted={report.get('coinbase_write_attempted')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
