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

from bot.config import BotConfig  # noqa: E402
from bot.full_bot_failure_determination_matrix import load_json_file  # noqa: E402
from bot.full_bot_fresh_judge_risk_evidence_runner import load_latest_inputs  # noqa: E402
from bot.full_bot_real_fresh_review_runner import (  # noqa: E402
    build_real_fresh_review_report,
    render_real_fresh_review_markdown,
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
        description="Run no-submit real fresh judge plus deterministic live-risk review for full-bot candidates."
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--d6-report", default="")
    parser.add_argument("--workflow-audit-report", default="")
    parser.add_argument("--failure-matrix-report", default="")
    parser.add_argument("--adapter-report", default="")
    parser.add_argument("--near-miss-review-report", default="")
    parser.add_argument("--orchestrator-report", default="")
    parser.add_argument("--no-llm-judge", action="store_true", help="Emit structured review requests without calling the LLM judge.")
    parser.add_argument("--judge-model", default="", help="Optional model override for the real judge call.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    return parser.parse_args(argv)


def _override(payloads: dict, paths: list[Path], key: str, raw: str) -> None:
    if not raw:
        return
    path = Path(raw)
    payloads[key] = load_json_file(path)
    paths.append(path)


def _judge_client_or_none(call_llm: bool) -> tuple[Optional[object], str, str]:
    if not call_llm:
        return None, "disabled_by_cli", ""
    try:
        cfg = BotConfig()
        cfg.validate()
        if not getattr(cfg, "openai_api_key", ""):
            return None, "missing_openai_api_key", getattr(cfg, "openai_judge_model", "") or getattr(cfg, "openai_model", "")
        from bot.llm_clients import ResilientLLMClient

        return ResilientLLMClient(cfg), "available", getattr(cfg, "openai_judge_model", "") or getattr(cfg, "openai_model", "")
    except Exception as exc:
        return None, f"unavailable:{exc}", ""


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

    call_llm = not args.no_llm_judge
    judge_client, judge_client_status, default_judge_model = _judge_client_or_none(call_llm)
    effective_judge_model = args.judge_model or default_judge_model or None
    report = build_real_fresh_review_report(
        root=root,
        judge_client=judge_client,
        judge_model=effective_judge_model,
        call_llm_judge=call_llm,
        source_paths=source_paths,
        **payloads,
    )
    report["judge_client_status"] = judge_client_status
    report["effective_judge_model"] = effective_judge_model or ""
    if call_llm and judge_client is None:
        report["blockers"] = sorted(set((report.get("blockers") or []) + ["llm_judge_client_unavailable"]))

    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_real_fresh_review_markdown(report)
    _atomic_write(Path(args.json_out), json_text.encode("utf-8"))
    _atomic_write(Path(args.markdown_out), markdown_text.encode("utf-8"))

    if args.markdown:
        print(markdown_text, end="")
    elif args.json:
        print(json_text, end="")
    else:
        print(
            "real_fresh_review "
            f"classification={report.get('classification')} "
            f"candidates={report.get('candidate_count')} "
            f"judge_approvals={len(report.get('judge_approvals') or [])} "
            f"risk_approvals={len(report.get('deterministic_live_risk_approvals') or [])} "
            f"phase_c_ready={len(report.get('phase_c_ready_candidates') or [])} "
            f"judge_client_status={judge_client_status} "
            f"live_order_submit_attempted={report.get('live_order_submit_attempted')} "
            f"coinbase_write_attempted={report.get('coinbase_write_attempted')} "
            f"state_write_performed={report.get('state_write_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
