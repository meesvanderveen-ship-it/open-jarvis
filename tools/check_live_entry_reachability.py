#!/usr/bin/env python3
"""
Phase 3 tool: Prove live entry route reachability (read-only, no side effects).

Checks every gate in the C4.3 entry path:
  1. autonomous_runtime_enabled compound flag (from .env / config)
  2. judge.decision == "approve_trade" reachability (from most recent cycle logs)
  3. Phase C guard hard blocks (static code inspection)
  4. C4.3 submit_allowed checks (static env inspection)
  5. CoinbaseClient.place_limit_order existence (import check)
  6. Prior submission evidence (phase_c_live_submit.jsonl)

Usage: python tools/check_live_entry_reachability.py [--out reports/audits/live-entry-reachability-latest.json]

Output: JSON + Markdown report. No orders are placed. No files are mutated.
"""

import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "reports" / "audits" / "live-entry-reachability-latest.json"
DEFAULT_MD = ROOT / "reports" / "audits" / "live-entry-reachability-latest.md"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _check_env_flags():
    env_file = ROOT / ".env"
    flags = {}
    if env_file.exists():
        for line in env_file.read_text(errors="replace").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                flags[k.strip()] = v.strip().strip('"').strip("'")
    return flags


def _boolish(v: str, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def check_autonomous_runtime_enabled(flags: dict):
    checks = {
        "enable_phase_c43_autonomous_entry_submitter": _boolish(flags.get("ENABLE_PHASE_C43_AUTONOMOUS_ENTRY_SUBMITTER", "true"), True),
        "enable_autonomous_small_live_orderbook_mode": _boolish(flags.get("ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE", "false")),
        "enable_phase_c_actual_coinbase_submit": _boolish(flags.get("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT", "false")),
        "enable_live_entry_orders": _boolish(flags.get("ENABLE_LIVE_ENTRY_ORDERS", "false")),
    }
    exits_enabled = _boolish(flags.get("ENABLE_LIVE_EXIT_ORDERS", "false"))
    if exits_enabled:
        full_wf = _boolish(flags.get("ENABLE_FULL_WORKFLOW_LIVE_MODE", "false"))
        allow_exits = _boolish(flags.get("AUTONOMOUS_ALLOW_EXITS", "false"))
        d3_exit = _boolish(flags.get("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false"))
        no_disable = not _boolish(flags.get("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true"))
        entry_only_first = _boolish(flags.get("AUTONOMOUS_ENTRY_ONLY_FIRST", "false"))
        checks["exits_enabled_with_full_workflow"] = full_wf and allow_exits and d3_exit and no_disable and not entry_only_first
    else:
        checks["exits_not_enabled_passes"] = True

    ack_value = "I_UNDERSTAND_AND_APPROVE_C43_RESTING_LIMIT_BUY_SUBMIT"
    actual_ack = flags.get("PHASE_C43_RUNTIME_SUBMIT_ACK", "")
    checks["phase_c43_runtime_submit_ack_correct"] = actual_ack == ack_value

    result = all(checks.values())
    return {
        "result": result,
        "checks": checks,
        "note": "autonomous_runtime_enabled would be True" if result else "autonomous_runtime_enabled would be False — check failing flags"
    }


def check_judge_reachability():
    """Check most recent cycle summary from loop.log."""
    loop_log = ROOT / "logs" / "loop.log"
    if not loop_log.exists():
        return {"result": "unknown", "reason": "logs/loop.log not found"}

    import re
    CYCLE_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Cycle summary \| "
        r"total=(\d+) \| errors=(\d+) \| approve_trade=(\d+) \| wait=(\d+)"
    )
    VIS_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Workflow visibility \| "
        r"valid_trade_plans=(\d+)"
    )

    last_cycle = None
    last_vis = None
    recent_approve = 0
    recent_total = 0
    recent_cycles = 0

    with open(loop_log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = CYCLE_RE.search(line)
            if m:
                ts, total, errors, approve, wait = m.groups()
                last_cycle = {"ts": ts, "total": int(total), "approve_trade": int(approve), "wait": int(wait)}
                if ts >= "2026-06-27":
                    recent_cycles += 1
                    recent_approve += int(approve)
                    recent_total += int(total)
                continue
            m = VIS_RE.search(line)
            if m:
                ts, vtp = m.groups()
                last_vis = {"ts": ts, "valid_trade_plans": int(vtp)}

    if last_cycle is None:
        return {"result": "unknown", "reason": "No cycle summaries found in loop.log"}

    return {
        "last_cycle": last_cycle,
        "last_visibility": last_vis,
        "recent_cycles_since_jun27": recent_cycles,
        "recent_approve_trade_count": recent_approve,
        "recent_total_analyses": recent_total,
        "judge_approves_at_all": recent_approve > 0,
        "current_status": "judge_always_waits" if recent_approve == 0 and recent_cycles > 0 else (
            "judge_sometimes_approves" if recent_approve > 0 else "insufficient_data"
        ),
        "blocker": "judge.decision=wait for all analyses" if recent_approve == 0 and recent_cycles > 0 else None,
    }


def check_coinbase_client():
    try:
        mod = importlib.import_module("bot.coinbase_client")
        client_cls = getattr(mod, "CoinbaseClient", None)
        if client_cls is None:
            return {"result": False, "reason": "CoinbaseClient class not found in bot.coinbase_client"}
        has_method = callable(getattr(client_cls, "place_limit_order", None))
        return {
            "result": has_method,
            "coinbase_client_importable": True,
            "place_limit_order_exists": has_method,
            "reason": "OK" if has_method else "place_limit_order method not found on CoinbaseClient",
        }
    except ImportError as e:
        return {"result": False, "reason": f"Import failed: {e}"}


def check_prior_submissions():
    submit_log = ROOT / "logs" / "phase_c_live_submit.jsonl"
    if not submit_log.exists():
        return {"found": False, "reason": "logs/phase_c_live_submit.jsonl not found"}

    submitted = []
    with open(submit_log, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") == "c43_autonomous_live_entry_submitted":
                submitted.append({
                    "ts": r.get("generated_at"),
                    "ticker": r.get("ticker"),
                    "live_order_submitted": r.get("live_order_submitted"),
                })

    return {
        "found": len(submitted) > 0,
        "count": len(submitted),
        "records": submitted,
        "last_submission": submitted[-1] if submitted else None,
    }


def check_guard_code():
    guard_file = ROOT / "bot" / "phase_c_live_guard.py"
    if not guard_file.exists():
        return {"result": "unknown", "reason": "bot/phase_c_live_guard.py not found"}

    content = guard_file.read_text(errors="replace")
    checks = {
        "evaluate_phase_c_live_entry_readiness_exists": "def evaluate_phase_c_live_entry_readiness" in content,
        "hard_block_wait_decision": "blocked_wait_decision" in content,
        "hard_block_valid_trade_plan": "blocked_valid_trade_plan" in content,
        "requires_approve_trade": "approve_trade" in content,
        "guard_allows_live_submit_key": "guard_allows_live_submit" in content,
    }
    return {"result": all(checks.values()), "checks": checks}


def run_all_checks():
    flags = _check_env_flags()

    runtime = check_autonomous_runtime_enabled(flags)
    judge = check_judge_reachability()
    coinbase = check_coinbase_client()
    submissions = check_prior_submissions()
    guard = check_guard_code()

    # Overall reachability
    path_technically_reachable = (
        runtime["result"] and
        coinbase.get("result", False) and
        guard.get("result", False)
    )

    current_blocker = None
    if not runtime["result"]:
        current_blocker = "autonomous_runtime_enabled=False — check env flags"
    elif not coinbase.get("result", False):
        current_blocker = "CoinbaseClient.place_limit_order not available"
    elif judge.get("current_status") == "judge_always_waits":
        current_blocker = "judge.decision=wait for all analyses — market conditions"

    return {
        "generated_at": _now_iso(),
        "report_type": "live_entry_reachability",
        "path_technically_reachable": path_technically_reachable,
        "current_active_blocker": current_blocker,
        "blocker_is_code_bug": current_blocker is not None and "market conditions" not in str(current_blocker),
        "gates": {
            "gate_1_autonomous_runtime_enabled": runtime,
            "gate_2_judge_approve_trade": judge,
            "gate_3_phase_c_guard": guard,
            "gate_4_coinbase_client": coinbase,
            "gate_5_prior_submissions_evidence": submissions,
        },
        "conclusion": "REACHABLE" if path_technically_reachable else "BLOCKED",
        "conclusion_detail": (
            f"Path is technically reachable. Active blocker: {current_blocker}"
            if path_technically_reachable and current_blocker
            else (
                "Path is reachable and no current blockers" if path_technically_reachable
                else f"Path is technically blocked: {current_blocker}"
            )
        ),
    }


def write_md(result: dict, path: Path):
    gates = result.get("gates", {})
    lines = [
        "# Live Entry Reachability Check",
        f"Generated: {result['generated_at']}",
        "",
        f"## Overall: {'✓ REACHABLE' if result['path_technically_reachable'] else '✗ BLOCKED'}",
        "",
        f"Active blocker: `{result.get('current_active_blocker') or 'none'}`",
        f"Blocker is code bug: `{result.get('blocker_is_code_bug', False)}`",
        "",
        "## Gate Results",
        "",
    ]

    g1 = gates.get("gate_1_autonomous_runtime_enabled", {})
    lines += [
        f"### Gate 1: autonomous_runtime_enabled",
        f"Result: {'✓ PASS' if g1.get('result') else '✗ FAIL'}",
        "",
    ]
    for k, v in g1.get("checks", {}).items():
        lines.append(f"- `{k}`: {'✓' if v else '✗'}")
    lines.append("")

    g2 = gates.get("gate_2_judge_approve_trade", {})
    lines += [
        "### Gate 2: judge approve_trade",
        f"Recent cycles (since Jun 27): {g2.get('recent_cycles_since_jun27', '?')}",
        f"approve_trade count: {g2.get('recent_approve_trade_count', '?')}",
        f"Status: {g2.get('current_status', '?')}",
        f"Active blocker: {g2.get('blocker', 'none')}",
        "",
    ]

    g4 = gates.get("gate_4_coinbase_client", {})
    lines += [
        f"### Gate 4: CoinbaseClient.place_limit_order",
        f"Result: {'✓ PASS' if g4.get('result') else '✗ FAIL'}  ({g4.get('reason', '')})",
        "",
    ]

    g5 = gates.get("gate_5_prior_submissions_evidence", {})
    lines += [
        "### Gate 5: Prior Submission Evidence",
        f"Successful submissions found: {g5.get('count', 0)}",
        f"Last submission: {g5.get('last_submission', 'none')}",
        "",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Check live entry reachability (read-only)")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--md", default=str(DEFAULT_MD))
    args = p.parse_args()

    print("Checking live entry reachability (read-only)...")
    result = run_all_checks()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"JSON written: {out}")

    md = Path(args.md)
    write_md(result, md)
    print(f"MD written: {md}")

    print(f"\nOverall: {'REACHABLE' if result['path_technically_reachable'] else 'BLOCKED'}")
    print(f"Active blocker: {result.get('current_active_blocker') or 'none'}")
    print(f"Blocker is code bug: {result.get('blocker_is_code_bug')}")

    return 0 if result["path_technically_reachable"] else 1


if __name__ == "__main__":
    sys.exit(main())
