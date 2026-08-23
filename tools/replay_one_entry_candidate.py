#!/usr/bin/env python3
"""
Phase 4 tool: Trace one best recent entry candidate through the full entry decision path.

Reads execution.jsonl to find the best recent ticker (closest to trigger with valid_trade_plan=True),
then traces it through all decision gates and produces a stage-by-stage report.

READ-ONLY. No orders placed. No state mutated.

Usage:
  python tools/replay_one_entry_candidate.py
  python tools/replay_one_entry_candidate.py --ticker SOL-USDC
  python tools/replay_one_entry_candidate.py --out reports/audits/one-candidate-entry-trace-latest.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXEC_LOG = ROOT / "logs" / "execution.jsonl"
LOOP_LOG = ROOT / "logs" / "loop.log"
DEFAULT_OUT = ROOT / "reports" / "audits" / "one-candidate-entry-trace-latest.json"
DEFAULT_MD = ROOT / "reports" / "audits" / "one-candidate-entry-trace-latest.md"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_recent_executions(ticker_filter=None, limit=200):
    """Read last N records from execution.jsonl."""
    if not EXEC_LOG.exists():
        return []

    # Read last chunk of file
    with open(EXEC_LOG, "rb") as f:
        size = f.seek(0, 2)
        start = max(0, size - 500_000)  # last 500KB
        f.seek(start)
        data = f.read().decode("utf-8", errors="replace")

    records = []
    for line in data.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ticker_filter and r.get("ticker") != ticker_filter:
            continue
        records.append(r)

    return records[-limit:]


def _find_best_candidate(records):
    """Find the ticker/record closest to its trigger with valid_trade_plan=True."""
    # Build per-ticker latest record
    by_ticker = {}
    for r in records:
        ticker = r.get("ticker")
        if not ticker:
            continue
        judge = r.get("judge") or {}
        if judge.get("decision") is None:
            continue
        if ticker not in by_ticker:
            by_ticker[ticker] = r

    # Score each ticker: prefer valid_trade_plan=True + closest to trigger
    best = None
    best_score = -1

    for ticker, r in by_ticker.items():
        judge = r.get("judge") or {}
        vtp = judge.get("valid_trade_plan") or (r.get("trade_plan") or {}).get("valid_trade_plan")
        obj = float(judge.get("objective_score") or 0)
        score = (1 if vtp else 0) * 100 + obj * 10
        if score > best_score:
            best_score = score
            best = (ticker, r)

    return best


def _extract_loop_log_reasons(ticker: str, limit_lines=5000):
    """Extract most recent judge reasons from loop.log for a ticker."""
    if not LOOP_LOG.exists():
        return {}

    import re
    JUDGE_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Ticker " +
        re.escape(ticker) + r" \| (gate|judge)_reasons=(.+)"
    )
    WARN_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - WARNING - Ticker " +
        re.escape(ticker) + r" \| gate_warnings=(.+)"
    )
    DECISION_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - INFO - Ticker " +
        re.escape(ticker) + r" \| gate=\S+ \| decision=(\w+) \| side=(\w+).*\| confidence=(\d+)"
    )

    results = {"decisions": [], "judge_reasons": [], "gate_warnings": []}

    with open(LOOP_LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line in lines[-limit_lines:]:
        m = DECISION_RE.search(line)
        if m:
            ts, dec, side, conf = m.groups()
            results["decisions"].append({"ts": ts, "decision": dec, "side": side, "confidence": int(conf)})
            continue
        m = JUDGE_RE.search(line)
        if m:
            ts, kind, text = m.groups()
            results["judge_reasons"].append({"ts": ts, "text": text[:500]})
            continue
        m = WARN_RE.search(line)
        if m:
            ts, text = m.groups()
            results["gate_warnings"].append({"ts": ts, "text": text[:500]})

    # Return only last few
    for k in results:
        results[k] = results[k][-5:]

    return results


def _trace_gates(r: dict, ticker: str):
    """Trace one execution record through all entry gates."""
    judge = r.get("judge") or {}
    trade_plan = r.get("trade_plan") or {}

    decision = str(judge.get("decision") or "").strip().lower()
    side = str(judge.get("side") or "").strip().upper()
    vtp_judge = judge.get("valid_trade_plan")
    vtp_plan = trade_plan.get("valid_trade_plan")
    valid_trade_plan = bool(vtp_judge or vtp_plan)
    objective_score = float(judge.get("objective_score") or 0)

    stages = []

    # Gate 1: valid_trade_plan
    stages.append({
        "gate": "valid_trade_plan",
        "pass": valid_trade_plan,
        "value": {"judge_vtp": vtp_judge, "plan_vtp": vtp_plan},
        "note": "After f13e1f7 fix: checks numeric price/size fields only" if valid_trade_plan else "Plan failed validation",
    })

    # Gate 2: judge decision
    stages.append({
        "gate": "judge_approve_trade",
        "pass": decision == "approve_trade",
        "value": {"decision": decision, "side": side, "confidence": judge.get("confidence"), "objective_score": objective_score},
        "prompt_rule_applicable": objective_score >= 0.08 and valid_trade_plan,
        "note": (
            "BLOCKER: judge says wait" if decision != "approve_trade" else "Judge approves — entry eligible"
        ),
    })

    # Gate 3: fresh_approve_gate
    guard_allows = decision == "approve_trade" and side == "BUY" and valid_trade_plan
    stages.append({
        "gate": "fresh_approve_gate",
        "pass": guard_allows,
        "value": {
            "decision_approve": decision == "approve_trade",
            "side_buy": side == "BUY",
            "valid_trade_plan": valid_trade_plan,
            "note": "guard_allows_live_submit assumed True when above conditions met",
        },
        "note": "BLOCKED by gate_2" if decision != "approve_trade" else "Would pass",
    })

    # Gate 4: OB planner (hypothetical)
    # We don't have live OB data here, but we can reason about it
    trigger = float(trade_plan.get("trigger_price") or 0)
    # Current price not always in execution.jsonl - extract from judge reasons if possible
    stages.append({
        "gate": "orderbook_planner_eligible",
        "pass": False,  # always False when decision=wait (judge side=NONE)
        "hypothetical_if_judge_approved": "Would depend on trigger_price vs current_mid. If trigger > mid → breakout_confirmation_wait → eligible=False",
        "trigger_price": trigger,
        "note": "Not evaluated — blocked before this stage by gate_2",
    })

    # Gate 5: C4.3 submission
    stages.append({
        "gate": "c43_live_submission",
        "pass": False,
        "note": "Not reached — blocked at gate_2",
    })

    return stages


def build_trace(ticker_filter=None):
    records = _read_recent_executions(ticker_filter=ticker_filter)

    if not records:
        return {
            "generated_at": _now_iso(),
            "error": f"No execution records found{f' for {ticker_filter}' if ticker_filter else ''}",
        }

    if ticker_filter:
        # Use most recent record for specified ticker
        target_record = records[-1]
        target_ticker = ticker_filter
    else:
        result = _find_best_candidate(records)
        if not result:
            return {"generated_at": _now_iso(), "error": "No suitable candidate found in recent execution records"}
        target_ticker, target_record = result

    loop_data = _extract_loop_log_reasons(target_ticker)
    stages = _trace_gates(target_record, target_ticker)

    judge = target_record.get("judge") or {}
    trade_plan = target_record.get("trade_plan") or {}

    return {
        "generated_at": _now_iso(),
        "report_type": "one_candidate_entry_trace",
        "candidate_ticker": target_ticker,
        "selection_method": "specified" if ticker_filter else "auto (best valid_trade_plan + highest objective_score)",
        "judge_summary": {
            "decision": judge.get("decision"),
            "side": judge.get("side"),
            "confidence": judge.get("confidence"),
            "objective_score": judge.get("objective_score"),
            "valid_trade_plan": judge.get("valid_trade_plan"),
            "strategy": judge.get("strategy"),
            "reasons": judge.get("reasons", [])[:5],
        },
        "trade_plan_summary": {
            "plan_action": trade_plan.get("plan_action"),
            "side": trade_plan.get("side"),
            "trigger_price": trade_plan.get("trigger_price"),
            "entry_zone_low": trade_plan.get("entry_zone_low"),
            "entry_zone_high": trade_plan.get("entry_zone_high"),
            "do_not_chase_above": trade_plan.get("do_not_chase_above"),
            "stop_loss_price": trade_plan.get("stop_loss_price"),
            "take_profit_1": trade_plan.get("take_profit_1"),
            "max_quote_size": trade_plan.get("max_quote_size"),
            "valid_trade_plan": trade_plan.get("valid_trade_plan"),
        },
        "gate_trace": stages,
        "loop_log_evidence": loop_data,
        "final_blocker": next((s["gate"] for s in stages if not s.get("pass")), None),
        "conclusion": (
            "E — No good candidates. Judge correctly waits for market confirmation."
            if judge.get("decision") == "wait"
            else "Unexpected state — review gate_trace"
        ),
    }


def write_md(result: dict, path: Path):
    lines = [
        "# One Candidate Entry Trace",
        f"Generated: {result['generated_at']}",
        f"Candidate: **{result.get('candidate_ticker', 'unknown')}**",
        f"Selection: {result.get('selection_method', '')}",
        "",
    ]

    if "error" in result:
        lines.append(f"**Error**: {result['error']}")
    else:
        js = result.get("judge_summary", {})
        lines += [
            "## Judge Summary",
            f"- decision: `{js.get('decision')}`",
            f"- side: `{js.get('side')}`",
            f"- confidence: {js.get('confidence')}",
            f"- objective_score: {js.get('objective_score')}",
            f"- valid_trade_plan: {js.get('valid_trade_plan')}",
            "",
            "## Gate Trace",
            "",
            "| Gate | Pass | Note |",
            "|------|------|------|",
        ]
        for s in result.get("gate_trace", []):
            icon = "✓" if s.get("pass") else "✗"
            note = str(s.get("note", ""))[:80]
            lines.append(f"| {s['gate']} | {icon} | {note} |")

        lines += [
            "",
            f"**Final blocker**: `{result.get('final_blocker', 'none')}`",
            "",
            "## Conclusion",
            "",
            result.get("conclusion", ""),
        ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="Trace one best recent entry candidate (read-only)")
    p.add_argument("--ticker", default=None, help="Specific ticker to trace (default: auto-select best)")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--md", default=str(DEFAULT_MD))
    args = p.parse_args()

    print(f"Tracing entry candidate{f' for {args.ticker}' if args.ticker else ' (auto-selecting best)'}...")
    result = build_trace(ticker_filter=args.ticker)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    print(f"JSON written: {out}")

    md = Path(args.md)
    write_md(result, md)
    print(f"MD written: {md}")

    if "error" in result:
        print(f"\nError: {result['error']}")
        return 1

    print(f"\nCandidate: {result['candidate_ticker']}")
    print(f"Decision: {result.get('judge_summary', {}).get('decision')}")
    print(f"First blocker: {result.get('final_blocker')}")
    print(f"Conclusion: {result.get('conclusion')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
