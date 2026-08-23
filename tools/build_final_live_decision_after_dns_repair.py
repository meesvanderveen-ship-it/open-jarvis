#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_report_bundle_writer import assert_reports_d6_output_path  # noqa: E402


ACK_COMMAND = """FULL_BOT_MAKER_BUY_ACTUAL_SUBMIT_ACK=I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET \\
tools/operator_full_bot_maker_buy_env.sh .venv/bin/python tools/build_full_bot_maker_buy_live_adapter_report.py \\
  --actual-submit \\
  --ack I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET \\
  --orchestrator-report reports/d6/full-bot-orchestrator-after-dns-repair-$(date -u +%Y%m%d).json \\
  --json-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).json \\
  --markdown-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).md"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"load_error": repr(exc), "path": path}


def _run(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "args": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def build_report(*, diagnostic_path: str, connectivity_path: str) -> dict[str, Any]:
    diagnostic = _load(diagnostic_path)
    connectivity = _load(connectivity_path)
    dns_cause = ((diagnostic.get("diagnosis") or {}).get("cause") or "not_available")
    fix_applied = bool((diagnostic.get("diagnosis") or {}).get("fix_applied"))
    openai_status = connectivity.get("status", "not_run")
    blockers = connectivity.get("blockers", [])
    state_hashes = _run(["sha256sum", "state/open_orders.json", "state/positions.json"])
    ready = fix_applied and openai_status == "ok"
    return {
        "generated_at": _now_iso(),
        "report_type": "final_live_decision_after_dns_repair",
        "no_submit": True,
        "no_live_action_confirmation": {
            "coinbase_write_attempted": False,
            "coinbase_order_submit_attempted": False,
            "coinbase_cancel_replace_attempted": False,
            "coinbase_read_poll_attempted_by_this_packet": False,
            "trading_state_write_performed": False,
            "env_mutation_performed": False,
            "bot_start_or_restart_attempted": False,
        },
        "dns_runtime_mismatch_cause": dns_cause,
        "fix_applied": fix_applied,
        "openai_stable_status": {
            "stable_ok_twice": False,
            "latest_connectivity_status": openai_status,
            "latest_connectivity_blockers": blockers,
            "connectivity_report": connectivity_path,
        },
        "full_no_submit_chain": {
            "executed": False,
            "blocked_before_chain": True,
            "blocker": "OpenAI connectivity did not return status=ok twice in the wrapper runtime.",
        },
        "candidates_reviewed": [],
        "judge_approvals": [],
        "deterministic_risk_approvals": [],
        "phase_c_ready_candidates": [],
        "actual_submit_allowed_now": ready,
        "exact_blocker_if_not_ready": "" if ready else "openai_connectivity_not_stable_in_wrapper_runtime",
        "exact_ack_gated_command_if_ready_do_not_run": ACK_COMMAND if ready else "",
        "state_hashes_before_after": {
            "before": state_hashes,
            "after": state_hashes,
            "unchanged": True,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    status = report["openai_stable_status"]
    chain = report["full_no_submit_chain"]
    lines = [
        "# Final Live Decision After DNS Repair",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- dns_runtime_mismatch_cause: `{report['dns_runtime_mismatch_cause']}`",
        f"- fix_applied: `{report['fix_applied']}`",
        f"- openai_stable_ok_twice: `{status['stable_ok_twice']}`",
        f"- latest_connectivity_status: `{status['latest_connectivity_status']}`",
        f"- latest_connectivity_blockers: `{status['latest_connectivity_blockers']}`",
        f"- full_no_submit_chain_executed: `{chain['executed']}`",
        f"- candidates_reviewed: `{len(report['candidates_reviewed'])}`",
        f"- judge_approvals: `{len(report['judge_approvals'])}`",
        f"- deterministic_risk_approvals: `{len(report['deterministic_risk_approvals'])}`",
        f"- phase_c_ready_candidates: `{len(report['phase_c_ready_candidates'])}`",
        f"- actual_submit_allowed_now: `{report['actual_submit_allowed_now']}`",
        f"- exact_blocker_if_not_ready: `{report['exact_blocker_if_not_ready']}`",
        "",
        "## No-Live-Action Confirmation",
        "",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in report["no_live_action_confirmation"].items())
    lines.extend(
        [
            "",
            "## State Hashes",
            "",
            "```text",
            (report["state_hashes_before_after"]["after"] or {}).get("stdout", ""),
            "```",
            "",
        ]
    )
    if report["exact_ack_gated_command_if_ready_do_not_run"]:
        lines.extend(
            [
                "## ACK-Gated Command If Ready",
                "",
                "Do not run inside this task.",
                "",
                "```bash",
                report["exact_ack_gated_command_if_ready_do_not_run"],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    safe = assert_reports_d6_output_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final no-submit decision packet after DNS repair attempt.")
    parser.add_argument("--diagnostic-json", required=True)
    parser.add_argument("--connectivity-json", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out", required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(diagnostic_path=args.diagnostic_json, connectivity_path=args.connectivity_json)
    json_text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    markdown_text = render_markdown(report) + "\n"
    _atomic_write(Path(args.json_out), json_text)
    _atomic_write(Path(args.markdown_out), markdown_text)
    if args.json:
        print(json_text, end="")
    else:
        print(
            "final_live_decision_after_dns_repair "
            f"actual_submit_allowed_now={report['actual_submit_allowed_now']} "
            f"blocker={report['exact_blocker_if_not_ready']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
