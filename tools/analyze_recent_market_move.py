#!/usr/bin/env python3
"""Phase 1 tool: quantify the realized market move of the last N hours per ticker,
using the bot's own recorded mid-price observations (logs/analysis.jsonl), and
classify whether it was an entry opportunity the bot could plausibly have taken.

No network calls, no writes to state/, no Coinbase calls. Read-only over logs/.

Usage:
    python3 tools/analyze_recent_market_move.py [--hours 72] [--out reports/audits/recent-market-move-latest.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_JSONL = ROOT / "logs" / "analysis.jsonl"
DEFAULT_OUT_JSON = ROOT / "reports" / "audits" / "recent-market-move-latest.json"
DEFAULT_OUT_MD = ROOT / "reports" / "audits" / "recent-market-move-latest.md"


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


def stream_ticker_series(hours: float) -> dict[str, list[dict]]:
    """Single streaming pass over logs/analysis.jsonl (can be very large — do
    not materialize the full parsed record, only the fields needed here)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    by_ticker: dict[str, list[dict]] = defaultdict(list)

    if not ANALYSIS_JSONL.exists():
        return by_ticker

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
            ticker = r.get("ticker")
            if not ticker:
                continue
            fp = r.get("feature_pack") or {}
            market = fp.get("market") or {}
            mid = market.get("mid_price")
            micro = fp.get("microstructure") or {}
            entry_gate = r.get("entry_gate") or {}
            judge = r.get("judge") or {}
            trade_plan = r.get("trade_plan") or {}
            try:
                mid_f = float(mid) if mid is not None else None
            except (TypeError, ValueError):
                mid_f = None
            if mid_f is None:
                continue
            by_ticker[ticker].append({
                "ts": r.get("generated_at"),
                "mid_price": mid_f,
                "spread_pct": market.get("spread_pct"),
                "vol_1h": _g(micro, "1h", "volume_vs_avg"),
                "entry_gate_decision": entry_gate.get("decision"),
                "judge_decision": judge.get("decision"),
                "plan_action": trade_plan.get("plan_action"),
            })
            del r, fp, market, micro

    for series in by_ticker.values():
        series.sort(key=lambda x: x["ts"])
    return by_ticker


def classify(move_pct: float, dd_pct: float, range_pct: float, avg_vol: float | None) -> str:
    if range_pct < 1.5:
        return "choppy_no_trade"
    if move_pct >= 5.0 and dd_pct > -3.0:
        return "strong_uptrend"
    if move_pct >= 5.0:
        return "breakout"
    if move_pct >= 2.0:
        return "slow_grind_up"
    if move_pct <= -2.0:
        return "downtrend"
    if abs(move_pct) < 2.0 and range_pct >= 3.0:
        return "choppy_no_trade"
    if move_pct > 0 and dd_pct <= -3.0:
        return "reclaim"
    return "choppy_no_trade"


def analyze(hours: float) -> dict:
    by_ticker = stream_ticker_series(hours)
    tickers = {}
    opportunity_count = 0

    for ticker, series in sorted(by_ticker.items()):
        if len(series) < 2:
            continue
        prices = [p["mid_price"] for p in series]
        start_price = prices[0]
        end_price = prices[-1]
        max_price = max(prices)
        min_price = min(prices)
        move_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0
        range_pct = (max_price - min_price) / min_price * 100 if min_price else 0.0
        # drawdown from running peak, expressed negative
        peak = prices[0]
        max_dd = 0.0
        peak_idx = 0
        trough_after_peak_idx = 0
        for idx, p in enumerate(prices):
            if p > peak:
                peak = p
                peak_idx = idx
            dd = (p - peak) / peak * 100 if peak else 0.0
            if dd < max_dd:
                max_dd = dd
                trough_after_peak_idx = idx

        vols = [p["vol_1h"] for p in series if isinstance(p.get("vol_1h"), (int, float))]
        avg_vol = sum(vols) / len(vols) if vols else None
        recent_vols = vols[-6:] if len(vols) >= 6 else vols
        early_vols = vols[:6] if len(vols) >= 6 else vols
        vol_trend = "rising" if (recent_vols and early_vols and sum(recent_vols) / len(recent_vols) > sum(early_vols) / len(early_vols)) else "flat_or_falling"

        spreads = [p["spread_pct"] for p in series if isinstance(p.get("spread_pct"), (int, float))]
        avg_spread_pct = (sum(spreads) / len(spreads) * 100) if spreads else None

        # ideal entry: the lowest price reached at/after the point the uptrend was
        # already recognizable (first 25% of the window), i.e. best realistic entry
        # a "wait for confirmation" strategy could have taken.
        quarter = max(1, len(prices) // 4)
        window_after_confirm = prices[quarter:] or prices
        ideal_entry_price = min(window_after_confirm)
        ideal_entry_idx = prices.index(ideal_entry_price, quarter if quarter < len(prices) else 0) if ideal_entry_price in prices[quarter:] else quarter
        upside_from_ideal_entry_pct = (end_price - ideal_entry_price) / ideal_entry_price * 100 if ideal_entry_price else 0.0

        # was this an entry opportunity: genuinely up, with meaningful realized upside
        # remaining after a plausible confirmation-delayed entry
        was_opportunity = move_pct > 1.5 and upside_from_ideal_entry_pct > 0.5

        setup_type = classify(move_pct, max_dd, range_pct, avg_vol)

        # explain why the bot didn't see it as a candidate, using the actual
        # recorded decisions from the window (not a guess)
        judge_decisions = [p["judge_decision"] for p in series if p.get("judge_decision")]
        plan_actions = [p["plan_action"] for p in series if p.get("plan_action")]
        gate_decisions = [p["entry_gate_decision"] for p in series if p.get("entry_gate_decision")]
        approve_count = sum(1 for d in judge_decisions if d == "approve_trade")
        prepare_count = sum(1 for a in plan_actions if str(a).startswith("prepare_"))
        gate_analyze_count = sum(1 for d in gate_decisions if d in {"analyze", "priority_analyze"})

        if was_opportunity and approve_count == 0:
            if prepare_count > 0:
                why_missed = (
                    f"Bot recognized the setup ({prepare_count}/{len(series)} cycles produced a valid "
                    f"prepare_* trade plan, {gate_analyze_count}/{len(series)} passed the hard gate) but the "
                    f"judge/promotion layer never converted any of them to approve_trade. "
                    f"See reports/audits/entry-funnel-72h-latest.md for the exact blocker."
                )
            elif gate_analyze_count > 0:
                why_missed = (
                    f"Hard gate flagged this ticker as worth analyzing in {gate_analyze_count}/{len(series)} "
                    f"cycles, but no valid trade plan was ever produced (planner returned no_plan every time)."
                )
            else:
                why_missed = (
                    "Hard gate never escalated this ticker to 'analyze' during the window "
                    "(stayed in watch/skip) despite the realized price move."
                )
        elif approve_count > 0:
            why_missed = f"Bot did approve_trade {approve_count} time(s) in this window."
        else:
            why_missed = "Move was not large/clean enough to count as a missed opportunity by this audit's criteria."

        if was_opportunity:
            opportunity_count += 1

        tickers[ticker] = {
            "n_observations": len(series),
            "start_price": start_price,
            "current_price": end_price,
            "move_pct_full_window": round(move_pct, 3),
            "move_pct_24h": round(
                (prices[-1] - prices[max(0, len(prices) - max(1, len(prices) // 3))]) /
                prices[max(0, len(prices) - max(1, len(prices) // 3))] * 100, 3
            ) if len(prices) >= 3 else None,
            "max_price": max_price,
            "min_price": min_price,
            "max_drawdown_pct": round(max_dd, 3),
            "range_pct": round(range_pct, 3),
            "avg_1h_volume_vs_avg": round(avg_vol, 3) if avg_vol is not None else None,
            "volume_trend": vol_trend,
            "avg_spread_pct": round(avg_spread_pct, 4) if avg_spread_pct is not None else None,
            "classification": setup_type,
            "was_entry_opportunity": was_opportunity,
            "ideal_entry_price": ideal_entry_price,
            "upside_from_ideal_entry_to_now_pct": round(upside_from_ideal_entry_pct, 3),
            "bot_gate_analyze_cycles": gate_analyze_count,
            "bot_valid_prepare_plan_cycles": prepare_count,
            "bot_approve_trade_cycles": approve_count,
            "why_bot_did_not_capture_this": why_missed,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "tickers": tickers,
        "summary": {
            "tickers_analyzed": len(tickers),
            "tickers_that_rose": sum(1 for t in tickers.values() if t["move_pct_full_window"] > 0),
            "tickers_classified_opportunity": opportunity_count,
            "tickers_with_any_approve_trade": sum(1 for t in tickers.values() if t["bot_approve_trade_cycles"] > 0),
            "classification_counts": {
                c: sum(1 for t in tickers.values() if t["classification"] == c)
                for c in {"strong_uptrend", "reclaim", "breakout", "slow_grind_up", "downtrend", "choppy_no_trade"}
            },
        },
    }


def write_md(result: dict, path: Path) -> None:
    s = result["summary"]
    lines = [
        "# Recent Market Move Audit",
        f"Generated: {result['generated_at']}  ",
        f"Window: last {result['window_hours']}h (from bot's own recorded mid-price observations)",
        "",
        "## Summary",
        f"- Tickers analyzed: {s['tickers_analyzed']}",
        f"- Tickers that rose: {s['tickers_that_rose']}/{s['tickers_analyzed']}",
        f"- Tickers classified as a real entry opportunity: {s['tickers_classified_opportunity']}",
        f"- Tickers with >=1 approve_trade in window: {s['tickers_with_any_approve_trade']}",
        "",
        "## Classification counts",
    ]
    for c, n in sorted(s["classification_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {c}: {n}")
    lines += [
        "",
        "## Per-ticker detail",
        "",
        "| Ticker | Move (window) | 24h | Max DD | Range | Class | Opportunity? | approve_trade | why not captured |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t, d in sorted(result["tickers"].items(), key=lambda kv: -kv[1]["move_pct_full_window"]):
        move_24h = "" if d["move_pct_24h"] is None else f"{d['move_pct_24h']:+.2f}%"
        lines.append(
            f"| {t} | {d['move_pct_full_window']:+.2f}% | "
            f"{move_24h} | "
            f"{d['max_drawdown_pct']:.2f}% | {d['range_pct']:.2f}% | {d['classification']} | "
            f"{'YES' if d['was_entry_opportunity'] else 'no'} | {d['bot_approve_trade_cycles']} | "
            f"{d['why_bot_did_not_capture_this'][:140]} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--out", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    result = analyze(args.hours)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"JSON written: {out_path}")

    md_path = Path(args.md)
    write_md(result, md_path)
    print(f"Markdown written: {md_path}")

    s = result["summary"]
    print(f"\n{s['tickers_that_rose']}/{s['tickers_analyzed']} tickers rose; "
          f"{s['tickers_classified_opportunity']} classified as real opportunities; "
          f"{s['tickers_with_any_approve_trade']} had any approve_trade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
