#!/usr/bin/env python3
"""Read-only LLM/API cost breakdown from logs/llm_cost_ledger.jsonl.

Aggregates the redacted metadata rows written by bot/llm_cost_ledger.py
(no prompt/completion content is ever read or printed — the ledger never
contains it). Pure read/aggregate: no Coinbase calls, no state writes, no
trading-state mutation, no LLM calls of its own.

Examples:
    python -m tools.show_llm_cost_breakdown --since 24h --json
    python -m tools.show_llm_cost_breakdown --since 7d --by agent --json
    python -m tools.show_llm_cost_breakdown --since 24h --by ticker --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "logs" / "llm_cost_ledger.jsonl"

_DURATION_RE = re.compile(r"^(\d+)\s*([smhd])$", re.IGNORECASE)
_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_since(value: str, *, now: Optional[datetime] = None) -> datetime:
    """Accepts a duration shorthand (e.g. '24h', '7d', '30m') or an ISO timestamp."""
    now = now or datetime.now(timezone.utc)
    value = (value or "").strip()
    match = _DURATION_RE.match(value)
    if match:
        amount, unit = match.groups()
        seconds = int(amount) * _DURATION_UNIT_SECONDS[unit.lower()]
        return now - timedelta(seconds=seconds)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        # Unparseable -- default to a generous 24h window rather than crashing
        # a read-only report.
        return now - timedelta(hours=24)


def _parse_row_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    raw = row.get("timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def load_ledger_rows(
    path: Path = DEFAULT_LEDGER_PATH, *, since: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if since is not None:
            ts = _parse_row_timestamp(obj)
            if ts is not None and ts < since:
                continue
        rows.append(obj)
    return rows


def _sum_cost(rows: Iterable[Dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            total += float(cost)
    return round(total, 6)


def _avg(values: List[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _group_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return dict(grouped)


def _group_summary(rows: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for group_key, group_rows in sorted(_group_by(rows, key).items()):
        token_totals = [r.get("total_tokens") for r in group_rows if isinstance(r.get("total_tokens"), (int, float))]
        out[group_key] = {
            "calls": len(group_rows),
            "estimated_cost_usd": _sum_cost(group_rows),
            "avg_tokens_per_call": _avg([float(t) for t in token_totals]),
            "no_action_calls": sum(1 for r in group_rows if r.get("was_call_necessary") == "no"),
            "error_calls": sum(1 for r in group_rows if r.get("call_outcome") not in (None, "success")),
        }
    return out


def detect_duplicate_first_attempts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flag (cycle_id, ticker, stage) combinations with more than one
    first-attempt (attempt=1) call -- a legitimate retry always increments
    `attempt`, so >1 distinct attempt=1 rows for the same cycle/ticker/stage
    indicates the same logical agent call was issued twice in one cycle."""
    first_attempts: Dict[tuple, int] = defaultdict(int)
    for row in rows:
        if row.get("attempt") == 1:
            key = (row.get("cycle_id"), row.get("ticker"), row.get("stage"))
            first_attempts[key] += 1
    return [
        {"cycle_id": key[0], "ticker": key[1], "stage": key[2], "first_attempt_count": count}
        for key, count in sorted(first_attempts.items())
        if count > 1
    ]


def build_cost_breakdown(
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    since: str = "24h",
    by: Optional[str] = None,
) -> Dict[str, Any]:
    since_dt = parse_since(since)
    rows = load_ledger_rows(ledger_path, since=since_dt)

    total_cost = _sum_cost(rows)
    total_calls = len(rows)
    no_action_rows = [r for r in rows if r.get("was_call_necessary") == "no"]
    no_action_cost = _sum_cost(no_action_rows)
    error_rows = [r for r in rows if r.get("call_outcome") not in (None, "success")]
    retried_rows = [r for r in rows if isinstance(r.get("attempt"), int) and r.get("attempt", 1) > 1]
    cache_hit_rows = [r for r in rows if r.get("cache_hit") is True]
    skipped_budget_rows = [r for r in rows if r.get("skipped_due_budget") is True]

    by_model = _group_summary(rows, "model")
    by_agent = _group_summary(rows, "agent")
    by_ticker = _group_summary(rows, "ticker")
    by_cycle = _group_summary(rows, "cycle_id")

    top_expensive = sorted(
        (r for r in rows if isinstance(r.get("estimated_cost_usd"), (int, float))),
        key=lambda r: r["estimated_cost_usd"],
        reverse=True,
    )[:10]
    top_expensive_redacted = [
        {
            "timestamp": r.get("timestamp"),
            "cycle_id": r.get("cycle_id"),
            "ticker": r.get("ticker"),
            "agent": r.get("agent"),
            "model": r.get("model"),
            "estimated_cost_usd": r.get("estimated_cost_usd"),
            "total_tokens": r.get("total_tokens"),
            "decision_result": r.get("decision_result"),
            "was_call_necessary": r.get("was_call_necessary"),
        }
        for r in top_expensive
    ]

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "service_restart_attempted": False,
        "ledger_path": str(ledger_path),
        "since": since,
        "since_resolved_utc": since_dt.isoformat(),
        "total_calls": total_calls,
        "total_estimated_cost_usd": total_cost,
        "avg_cost_per_call_usd": round(total_cost / total_calls, 8) if total_calls else 0.0,
        "calls_per_cycle": _avg([float(v["calls"]) for v in by_cycle.values()]),
        "no_action_calls": len(no_action_rows),
        "no_action_cost_usd": no_action_cost,
        "no_action_cost_pct": round((no_action_cost / total_cost * 100.0), 2) if total_cost else 0.0,
        "error_calls": len(error_rows),
        "retried_attempts": len(retried_rows),
        "cache_hit_calls": len(cache_hit_rows),
        "skipped_due_budget_calls": len(skipped_budget_rows),
        "by_model": by_model,
        "by_agent": by_agent,
        "by_ticker": by_ticker,
        "by_cycle": by_cycle,
        "top_10_expensive_calls": top_expensive_redacted,
        "duplicate_call_candidates": detect_duplicate_first_attempts(rows),
        "recommendations": _build_recommendations(by_agent, no_action_cost, total_cost, retried_rows, total_calls),
    }

    if by:
        key_map = {"agent": "by_agent", "ticker": "by_ticker", "model": "by_model", "cycle": "by_cycle"}
        selected_key = key_map.get(by)
        if selected_key:
            report["selected_breakdown_by"] = by
            report["selected_breakdown"] = report[selected_key]

    return report


def _build_recommendations(
    by_agent: Dict[str, Dict[str, Any]],
    no_action_cost: float,
    total_cost: float,
    retried_rows: List[Dict[str, Any]],
    total_calls: int,
) -> List[str]:
    recs: List[str] = []
    if total_cost > 0 and no_action_cost / total_cost > 0.3:
        recs.append(
            "no_action_cost_pct_above_30pct: a large share of spend produced no trading action "
            "(wait/no_trade/skip/reject) -- consider tightening the expensive-judge gate "
            "(_should_call_expensive_judge in bot/strategy_engine.py) or the entry-gate threshold."
        )
    if total_calls and len(retried_rows) / total_calls > 0.1:
        recs.append(
            "retry_rate_above_10pct: many calls needed a second/third provider attempt "
            "(re-billed each time) -- investigate JSON-corruption causes per agent rather than "
            "relying on retries."
        )
    sorted_agents = sorted(by_agent.items(), key=lambda kv: kv[1].get("estimated_cost_usd", 0.0), reverse=True)
    if sorted_agents:
        top_agent, top_stats = sorted_agents[0]
        if total_cost > 0 and top_stats.get("estimated_cost_usd", 0.0) / total_cost > 0.4:
            recs.append(
                f"single_agent_dominates_spend: '{top_agent}' accounts for "
                f"{round(top_stats.get('estimated_cost_usd', 0.0) / total_cost * 100, 1)}% of cost in window."
            )
    duplicated_full_stack = {"analyst_regime", "analyst_trend", "analyst_breakout", "analyst_meanrev", "analyst_bull", "analyst_bear", "analyst_synth"}
    if any(a in by_agent for a in duplicated_full_stack):
        recs.append(
            "full_feature_pack_resent_per_analyst: the analyst dossier (feature_pack/deepseek_pack/"
            "reflections/decision_outcomes) is re-serialized in full to all 6 analysts + synth + "
            "planner + judge with no delta/summary reuse -- see audit finding "
            "'duplicate_context_across_layers' in reports/audits/multi-agent-prompt-audit-latest.json."
        )
    if not recs:
        recs.append("no_high_confidence_waste_pattern_detected_in_window")
    return recs


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# LLM Cost Breakdown",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Window: since `{report.get('since')}` (resolved `{report.get('since_resolved_utc')}`)",
        "",
        "## Totals",
        f"- total_calls: {report.get('total_calls')}",
        f"- total_estimated_cost_usd: {report.get('total_estimated_cost_usd')}",
        f"- avg_cost_per_call_usd: {report.get('avg_cost_per_call_usd')}",
        f"- calls_per_cycle: {report.get('calls_per_cycle')}",
        f"- no_action_cost_pct: {report.get('no_action_cost_pct')}%",
        f"- error_calls: {report.get('error_calls')}",
        f"- retried_attempts: {report.get('retried_attempts')}",
        "",
        "## Cost by agent",
    ]
    for agent, stats in (report.get("by_agent") or {}).items():
        lines.append(f"- `{agent}`: {stats}")
    lines.extend(["", "## Cost by model"])
    for model, stats in (report.get("by_model") or {}).items():
        lines.append(f"- `{model}`: {stats}")
    lines.extend(["", "## Recommendations"])
    for rec in report.get("recommendations") or []:
        lines.append(f"- {rec}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only LLM/API cost breakdown report.")
    parser.add_argument("--since", default="24h", help="Duration shorthand (24h, 7d, 30m) or ISO timestamp")
    parser.add_argument("--by", choices=["agent", "ticker", "model", "cycle"], default=None)
    parser.add_argument("--ledger-path", default=str(DEFAULT_LEDGER_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_cost_breakdown(ledger_path=Path(args.ledger_path), since=args.since, by=args.by)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        out_path = Path(args.md_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_markdown(report), encoding="utf-8")
    if args.json or not (args.json_out or args.md_out):
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
