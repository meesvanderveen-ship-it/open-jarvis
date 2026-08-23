#!/usr/bin/env python3
"""Replay and summarise recent full-cycle decision traces.

Reads logs/analysis.jsonl and produces a human-readable trace of:
  - entry_gate decision (A)
  - analyst scores (B)
  - trade plan (C)
  - judge gate check (D)
  - judge decision (E)
  - post-judge overrides (F)
  - final valid_trade_plan / submission outcome (G)

Usage:
    python3 tools/replay_recent_decision_trace.py [--n 10] [--ticker BTC-USDC] [--json]

No writes. No Coinbase calls. No state mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_JSONL = _ROOT / "logs" / "analysis.jsonl"
_CYCLE_JSONL = _ROOT / "logs" / "cycle_summary.jsonl"


def _tail_jsonl(path: Path, n: int = 50, ticker: str | None = None) -> list[dict]:
    """Read last N parseable JSONL records efficiently by seeking from end of file."""
    if not path.is_file():
        return []
    # Seek backwards in chunks to find the last N lines without reading the whole file
    chunk = 1024 * 256  # 256 KB per seek
    records: list[dict] = []
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            pos = file_size
            buf = b""
            while pos > 0 and len(records) < n * 3:  # overshoot, filter later
                read_size = min(chunk, pos)
                pos -= read_size
                fh.seek(pos)
                buf = fh.read(read_size) + buf
                lines = buf.split(b"\n")
                # Keep first partial line for next iteration
                buf = lines[0]
                for line in reversed(lines[1:]):
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                        if isinstance(row, dict):
                            records.append(row)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if len(records) >= n * 3:
                        break
    except OSError:
        return []
    # records are in reverse order; reverse to get chronological
    records = list(reversed(records))
    if ticker:
        records = [r for r in records if r.get("ticker") == ticker]
    return records[-n:]


def _fmt_float(v: Any, decimals: int = 4) -> str:
    if v is None:
        return "None"
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def _trace_record(rec: dict) -> dict:
    ticker = rec.get("ticker", "UNKNOWN")
    ts = rec.get("generated_at", "")

    # A — Gate
    gate = rec.get("entry_gate") or {}
    gate_decision = gate.get("decision", "?")
    gate_conf = gate.get("confidence", "?")
    gate_setup = gate.get("setup_type", "?")

    # B — Analyst scores
    synth = rec.get("synth") or {}
    synth_conf = synth.get("synth_confidence") or synth.get("confidence")
    bull = rec.get("bull") or {}
    bull_score = bull.get("bull_score") or bull.get("score")
    bear = rec.get("bear") or {}
    bear_score = bear.get("bear_score") or bear.get("score")
    regime = rec.get("regime") or {}
    regime_label = regime.get("regime") or regime.get("market_regime")

    # C — Trade plan
    tp = rec.get("trade_plan") or {}
    plan_action = tp.get("plan_action", "?")
    plan_side = tp.get("side", "?")
    plan_entry_low = tp.get("entry_zone_low")
    plan_entry_high = tp.get("entry_zone_high")
    plan_trigger = tp.get("trigger_price")
    plan_stop = tp.get("stop_loss_price") or tp.get("stop_loss")
    plan_tp1 = tp.get("take_profit_1")
    plan_max_quote = tp.get("max_quote_size") or tp.get("max_size_quote")
    plan_confidence = tp.get("planner_confidence") or tp.get("confidence")
    plan_valid = tp.get("valid_trade_plan")

    # E — Judge
    jdg = rec.get("judge") or {}
    judge_decision = jdg.get("decision", "?")
    judge_valid_tp = jdg.get("valid_trade_plan")
    judge_response_valid_tp = jdg.get("judge_response_valid_trade_plan")
    judge_obj = jdg.get("objective_score")
    judge_edge = jdg.get("expected_edge_score")
    judge_conf = jdg.get("confidence")
    judge_size_quote = jdg.get("size_quote")
    judge_reasons = jdg.get("judge_reasons") or []
    judge_trigger_wait_reason = jdg.get("trigger_wait_reason")
    expensive_judge = jdg.get("expensive_judge_called")

    return {
        "ticker": ticker,
        "timestamp": ts,
        "A_gate": {
            "decision": gate_decision,
            "confidence": gate_conf,
            "setup_type": gate_setup,
        },
        "B_analysts": {
            "regime": regime_label,
            "synth_confidence": synth_conf,
            "bull_score": bull_score,
            "bear_score": bear_score,
        },
        "C_plan": {
            "plan_action": plan_action,
            "side": plan_side,
            "entry_zone": f"{_fmt_float(plan_entry_low, 2)}-{_fmt_float(plan_entry_high, 2)}",
            "trigger_price": _fmt_float(plan_trigger, 2),
            "stop_loss": _fmt_float(plan_stop, 2),
            "take_profit_1": _fmt_float(plan_tp1, 2),
            "max_quote_size": _fmt_float(plan_max_quote, 2),
            "planner_confidence": plan_confidence,
            "plan_valid_trade_plan": plan_valid,
        },
        "D_gate_check": {
            "expensive_judge_called": expensive_judge,
        },
        "E_judge": {
            "decision": judge_decision,
            "valid_trade_plan": judge_valid_tp,
            "judge_response_valid_trade_plan": judge_response_valid_tp,
            "objective_score": judge_obj,
            "expected_edge_score": judge_edge,
            "confidence": judge_conf,
            "size_quote": judge_size_quote,
            "trigger_wait_reason": judge_trigger_wait_reason,
            "judge_reasons": judge_reasons[:3] if judge_reasons else [],
        },
        "G_outcome": {
            "final_decision": judge_decision,
            "final_valid": judge_valid_tp,
            "submitted": judge_decision == "approve_trade" and bool(judge_valid_tp),
        },
    }


def _print_trace(t: dict) -> None:
    print(f"\n{'='*72}")
    print(f"  {t['ticker']}  |  {t['timestamp']}")
    print(f"{'='*72}")

    g = t["A_gate"]
    print(f"[A] GATE:    {g['decision']} (conf={g['confidence']}, setup={g['setup_type']})")

    b = t["B_analysts"]
    print(f"[B] ANALYSTS: regime={b['regime']}, synth={b['synth_confidence']}, "
          f"bull={b['bull_score']}, bear={b['bear_score']}")

    c = t["C_plan"]
    print(f"[C] PLAN:    {c['plan_action']} | side={c['side']} | "
          f"entry={c['entry_zone']} | trigger={c['trigger_price']}")
    print(f"             stop={c['stop_loss']} | tp1={c['take_profit_1']} | "
          f"quote={c['max_quote_size']} | conf={c['planner_confidence']}")
    print(f"             plan_valid={c['plan_valid_trade_plan']}")

    d = t["D_gate_check"]
    print(f"[D] GATE:    expensive_judge_called={d['expensive_judge_called']}")

    e = t["E_judge"]
    print(f"[E] JUDGE:   {e['decision']} | valid={e['valid_trade_plan']} | "
          f"obj={_fmt_float(e['objective_score'], 4)} | edge={_fmt_float(e['expected_edge_score'], 4)}")
    print(f"             conf={e['confidence']} | size_quote={e['size_quote']}")
    if e.get("trigger_wait_reason"):
        print(f"             trigger_wait: {e['trigger_wait_reason']}")
    for i, r in enumerate(e.get("judge_reasons") or []):
        print(f"             reason[{i}]: {str(r)[:100]}")

    go = t["G_outcome"]
    submitted_str = "YES — SUBMITTED" if go["submitted"] else "NO"
    print(f"[G] OUTCOME: decision={go['final_decision']} | submitted={submitted_str}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recent decision traces from logs/analysis.jsonl")
    parser.add_argument("--n", type=int, default=10, help="Number of recent records to show (default: 10)")
    parser.add_argument("--ticker", type=str, default=None, help="Filter by ticker (e.g. BTC-USDC)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON instead of human-readable")
    parser.add_argument("--log", type=str, default=str(_ANALYSIS_JSONL), help="Path to analysis.jsonl")
    args = parser.parse_args()

    log_path = Path(args.log)
    records = _tail_jsonl(log_path, n=args.n, ticker=args.ticker)

    if not records:
        print(f"No records found at {log_path}", file=sys.stderr)
        sys.exit(1)

    # Most recent first
    records = list(reversed(records))

    traces = [_trace_record(r) for r in records]

    if args.as_json:
        print(json.dumps({"traces": traces, "count": len(traces)}, indent=2, default=str))
        return

    print(f"\nDecision Trace Replay — {len(traces)} records from {log_path.name}")
    if args.ticker:
        print(f"Filtered to ticker: {args.ticker}")

    for t in traces:
        _print_trace(t)

    # Summary stats
    submitted = sum(1 for t in traces if t["G_outcome"]["submitted"])
    approved = sum(1 for t in traces if t["E_judge"]["decision"] == "approve_trade")
    valid_plans = sum(1 for t in traces if t["C_plan"]["plan_valid_trade_plan"])

    print(f"\n{'='*72}")
    print(f"SUMMARY: {len(traces)} records | valid_plans={valid_plans} | "
          f"approve_trade={approved} | submitted={submitted}")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
