#!/usr/bin/env python3
"""Phase 2 tool: reconstruct the exact entry funnel over a recent window,
directly from logs/analysis.jsonl (one record per ticker per cycle, containing
the full entry_gate -> analysts -> trade_plan -> judge chain).

This supersedes the earlier loop.log-regex version: loop.log only has
approve/wait totals per cycle, not per-ticker plan/judge detail or the exact
rejection reason. logs/analysis.jsonl has the full record.

Stages:
  0 scanned                 every ticker-cycle in the window
  1 hard_gate_pass           entry_gate.decision in {analyze, priority_analyze}
  2 expensive_judge_called   trade planner + judge were actually invoked
  3 trade_plan_produced      planner returned a real prepare_*/entry plan (not no_plan)
  4 valid_trade_plan         is_valid_entry_trade_plan() == True
  5 judge_approve_trade      final judge decision == approve_trade (post-promotion)
  6 c43_submit_attempted     logs/phase_c_live_submit.jsonl has a record in-window
  7 c43_submit_accepted      live_order_submitted == True
  8 position_opened          resulting position present in state/positions.json

Also reports: D2 (phase_d2_position_executor economics) does NOT run in the
entry path at all -- assess_minimum_net_edge() is only called when building
exit brackets for an already-open position (bot/phase_d2_position_executor.py
build_multi_exit_bracket_lite_plan). It cannot be the reason entries are
blocked, and this tool reports that explicitly rather than guessing.

No writes to state/. No Coinbase calls. No live order submission.

Usage:
    python3 tools/trace_entry_funnel.py [--hours 72] [--out reports/audits/entry-funnel-72h-latest.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_JSONL = ROOT / "logs" / "analysis.jsonl"
SUBMIT_LOG = ROOT / "logs" / "phase_c_live_submit.jsonl"
POSITIONS_PATH = ROOT / "state" / "positions.json"
DEFAULT_OUT_JSON = ROOT / "reports" / "audits" / "entry-funnel-72h-latest.json"
DEFAULT_OUT_MD = ROOT / "reports" / "audits" / "entry-funnel-72h-latest.md"

ENTRY_PLAN_ACTIONS = {
    "prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion",
    "prepare_resting_limit_entry", "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry", "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _g(d: dict, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def stream_records(hours: float):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    if not ANALYSIS_JSONL.exists():
        return
    with ANALYSIS_JSONL.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"generated_at"' not in line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(r.get("generated_at"))
            if ts is None or ts < cutoff:
                continue
            yield r


def _read_submit_log(hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    if not SUBMIT_LOG.exists():
        return out
    with SUBMIT_LOG.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(r.get("generated_at"))
            out.append({
                "ts": r.get("generated_at"),
                "in_window": bool(ts and ts >= cutoff),
                "ticker": r.get("ticker"),
                "status": r.get("status"),
                "live_order_submitted": r.get("live_order_submitted"),
            })
    return out


def build_funnel(hours: float) -> dict:
    per_ticker = defaultdict(lambda: {
        "scanned": 0, "hard_gate_pass": 0, "expensive_judge_called": 0,
        "trade_plan_produced": 0, "valid_trade_plan": 0, "judge_approve_trade": 0,
        "judge_wait": 0, "judge_reject": 0,
    })
    reject_reasons_at_gate: Counter = Counter()
    reject_reasons_at_plan: Counter = Counter()
    reject_reasons_at_judge: Counter = Counter()
    wait_reason_examples: list[dict] = []

    stage_counts = Counter()
    n = 0

    for r in stream_records(hours):
        n += 1
        ticker = r.get("ticker") or "UNKNOWN"
        pt = per_ticker[ticker]
        pt["scanned"] += 1
        stage_counts["scanned"] += 1

        entry_gate = r.get("entry_gate") or {}
        gate_decision = str(entry_gate.get("decision", "")).strip().lower()
        gate_pass = gate_decision in {"analyze", "priority_analyze"}
        if gate_pass:
            pt["hard_gate_pass"] += 1
            stage_counts["hard_gate_pass"] += 1
        else:
            reject_reasons_at_gate[gate_decision or "unknown"] += 1
            continue

        judge = r.get("judge") or {}
        expensive_called = bool(judge.get("expensive_judge_called"))
        if expensive_called:
            pt["expensive_judge_called"] += 1
            stage_counts["expensive_judge_called"] += 1
        else:
            reject_reasons_at_plan[judge.get("judge_skip_reason") or "expensive_judge_gate_skip"] += 1
            continue

        trade_plan = r.get("trade_plan") or {}
        plan_action = str(trade_plan.get("plan_action") or "no_plan").lower()
        plan_produced = plan_action in ENTRY_PLAN_ACTIONS
        if plan_produced:
            pt["trade_plan_produced"] += 1
            stage_counts["trade_plan_produced"] += 1
        else:
            reject_reasons_at_plan[f"planner_returned_{plan_action}"] += 1
            continue

        plan_valid = bool(trade_plan.get("valid_trade_plan"))
        if plan_valid:
            pt["valid_trade_plan"] += 1
            stage_counts["valid_trade_plan"] += 1
        else:
            reject_reasons_at_plan["is_valid_entry_trade_plan_false"] += 1
            continue

        judge_decision = str(judge.get("decision") or "").lower()
        if judge_decision == "approve_trade":
            pt["judge_approve_trade"] += 1
            stage_counts["judge_approve_trade"] += 1
        elif judge_decision == "wait":
            pt["judge_wait"] += 1
            stage_counts["judge_wait"] += 1
            reasons = judge.get("judge_reasons") or judge.get("reasons") or []
            substantive_reasons = [r for r in reasons if not str(r).startswith("objective_score=")]
            top_reason = (
                judge.get("trigger_wait_reason")
                or (substantive_reasons[0] if substantive_reasons else None)
                or (reasons[0] if reasons else "no_reason_recorded")
            )
            reject_reasons_at_judge[str(top_reason)[:160]] += 1
            if len(wait_reason_examples) < 12:
                wait_reason_examples.append({
                    "ticker": ticker,
                    "ts": r.get("generated_at"),
                    "plan_action": plan_action,
                    "setup_type": judge.get("setup_type") or trade_plan.get("setup_type"),
                    "objective_score": judge.get("objective_score"),
                    "trigger_wait_reason": judge.get("trigger_wait_reason"),
                    "top_reason": str(top_reason)[:200],
                })
        else:
            pt["judge_reject"] += 1
            stage_counts["judge_reject"] += 1
            reject_reasons_at_judge[f"judge_decision_{judge_decision or 'unknown'}"] += 1

    submit_records = _read_submit_log(hours)
    submit_in_window = [s for s in submit_records if s["in_window"]]
    submit_attempted = len(submit_in_window)
    submit_accepted = sum(1 for s in submit_in_window if s.get("live_order_submitted") is True)

    days_since_last_submit_log = None
    if submit_records:
        last_ts = _parse_ts(submit_records[-1]["ts"])
        if last_ts:
            days_since_last_submit_log = round((datetime.now(timezone.utc) - last_ts).total_seconds() / 86400, 1)

    stage_counts["c43_submit_attempted"] = submit_attempted
    stage_counts["c43_submit_accepted"] = submit_accepted

    open_positions = 0
    if POSITIONS_PATH.exists():
        try:
            positions = json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
            open_positions = sum(
                1 for p in positions.values()
                if isinstance(p, dict) and str(p.get("status", "")).lower() == "open"
            )
        except (json.JSONDecodeError, OSError):
            pass
    stage_counts["position_opened"] = open_positions

    # identify the sharpest N->0 (or N->near-0) drop for the headline bottleneck
    ordered_stages = [
        "scanned", "hard_gate_pass", "expensive_judge_called", "trade_plan_produced",
        "valid_trade_plan", "judge_approve_trade", "c43_submit_attempted",
        "c43_submit_accepted", "position_opened",
    ]
    bottleneck_stage = None
    bottleneck_from = None
    for i in range(1, len(ordered_stages)):
        prev_v = stage_counts[ordered_stages[i - 1]]
        cur_v = stage_counts[ordered_stages[i]]
        if prev_v > 0 and cur_v == 0:
            bottleneck_stage = ordered_stages[i]
            bottleneck_from = ordered_stages[i - 1]
            break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "funnel_stages": dict(stage_counts),
        "funnel_order": ordered_stages,
        "bottleneck": {
            "from_stage": bottleneck_from,
            "to_stage": bottleneck_stage,
            "drop": f"{stage_counts.get(bottleneck_from, '?')} -> 0" if bottleneck_stage else None,
        } if bottleneck_stage else None,
        "d2_economics_note": (
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT / PHASE_D2_MIN_REWARD_TO_FEE_RATIO / "
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO are evaluated only in "
            "bot/phase_d2_position_executor.py:build_multi_exit_bracket_lite_plan(), which runs "
            "AFTER a position is already open (building TP/SL exit brackets). assess_minimum_net_edge() "
            "has zero call sites in the entry path (strategy_engine.py, trade_planner.py, "
            "execution_planner.py). D2 economics thresholds are not a factor in why entries are blocked."
        ),
        "c43_submit_log": {
            "records_in_window": submit_attempted,
            "accepted_in_window": submit_accepted,
            "days_since_last_c43_submit_log_entry_of_any_kind": days_since_last_submit_log,
            "note": (
                "0 records of ANY kind (attempted, blocked, or submitted) in "
                f"logs/phase_c_live_submit.jsonl for {days_since_last_submit_log} days means C4.3 is never "
                "even being invoked -- consistent with the funnel dying upstream at judge_approve_trade=0."
            ) if submit_attempted == 0 else "C4.3 was invoked in this window.",
        },
        "per_ticker": dict(per_ticker),
        "reject_reasons_at_gate": dict(reject_reasons_at_gate.most_common(10)),
        "reject_reasons_at_plan": dict(reject_reasons_at_plan.most_common(10)),
        "reject_reasons_at_judge": dict(reject_reasons_at_judge.most_common(15)),
        "wait_reason_examples": wait_reason_examples,
        "records_scanned": n,
    }


def write_md(funnel: dict, path: Path) -> None:
    f = funnel["funnel_stages"]
    lines = [
        "# Entry Funnel Trace (72h, per-record)",
        f"Generated: {funnel['generated_at']}  ",
        f"Window: last {funnel['window_hours']}h, {funnel['records_scanned']} ticker-cycles scanned",
        "",
        "## Funnel",
        "```",
    ]
    for stage in funnel["funnel_order"]:
        marker = ""
        if funnel.get("bottleneck") and funnel["bottleneck"]["to_stage"] == stage:
            marker = "   <-- BOTTLENECK (drops to 0 here)"
        lines.append(f"{stage:28s} {f.get(stage, 0):5d}{marker}")
    lines.append("```")
    lines.append("")
    lines.append("## D2 economics note")
    lines.append(funnel["d2_economics_note"])
    lines.append("")
    lines.append("## C4.3 submit log")
    lines.append(f"- records in window: {funnel['c43_submit_log']['records_in_window']}")
    lines.append(f"- accepted in window: {funnel['c43_submit_log']['accepted_in_window']}")
    lines.append(f"- days since last C4.3 submit-log entry of any kind: "
                  f"{funnel['c43_submit_log']['days_since_last_c43_submit_log_entry_of_any_kind']}")
    lines.append(f"- {funnel['c43_submit_log']['note']}")
    lines.append("")
    lines.append("## Top rejection reasons at judge stage (valid plan -> wait)")
    for reason, count in funnel["reject_reasons_at_judge"].items():
        lines.append(f"- ({count}x) {reason}")
    lines.append("")
    lines.append("## Per-ticker funnel")
    lines.append("| Ticker | scanned | gate_pass | judge_called | plan_produced | valid_plan | approve_trade | wait |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for t, d in sorted(funnel["per_ticker"].items()):
        lines.append(
            f"| {t} | {d['scanned']} | {d['hard_gate_pass']} | {d['expensive_judge_called']} | "
            f"{d['trade_plan_produced']} | {d['valid_trade_plan']} | {d['judge_approve_trade']} | {d['judge_wait']} |"
        )
    lines.append("")
    lines.append("## Example wait decisions on valid plans (up to 12)")
    for ex in funnel["wait_reason_examples"]:
        lines.append(f"- **{ex['ticker']}** {ex['ts']} | plan={ex['plan_action']} | setup={ex['setup_type']} | "
                      f"objective_score={ex['objective_score']} | {ex['top_reason']}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--out", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    print(f"Tracing entry funnel over last {args.hours}h from {ANALYSIS_JSONL} ...")
    funnel = build_funnel(args.hours)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(funnel, indent=2, default=str), encoding="utf-8")
    print(f"JSON written: {out_path}")

    md_path = Path(args.md)
    write_md(funnel, md_path)
    print(f"Markdown written: {md_path}")

    f = funnel["funnel_stages"]
    print(f"\nFunnel: {' -> '.join(f'{s}={f.get(s,0)}' for s in funnel['funnel_order'])}")
    if funnel.get("bottleneck"):
        b = funnel["bottleneck"]
        print(f"BOTTLENECK: {b['from_stage']} -> {b['to_stage']} ({b['drop']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
