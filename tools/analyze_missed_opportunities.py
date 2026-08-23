#!/usr/bin/env python3
"""Phase 3 tool: label every wait/reject decision over a recent window against
REALIZED forward price action (1h/4h/12h/24h/72h), using the bot's own recorded
mid-price series as the source of truth (logs/analysis.jsonl). No network calls.

Labels (per the audit taxonomy):
  good_wait                    price fell or went nowhere after the wait
  missed_opportunity           price ran meaningfully in the planned direction
  too_conservative              small favorable move happened but bot never engaged
  blocked_by_judge              generic judge conservatism, no more specific reason found
  blocked_by_D2                 (see note: D2 does not run pre-entry; always 0, reported explicitly)
  blocked_by_reward_fee         judge/D2 text cited reward/fee ratio
  blocked_by_reward_risk        judge/D2 text cited reward/risk ratio
  blocked_by_spread             spread_pct exceeded max_spread_pct at decision time
  blocked_by_trigger_confirmation  judge explicitly waiting for a breakout/reclaim trigger/close
  blocked_by_cost_budget        judge/skip reason cited LLM cost budget
  blocked_by_config_live_flag   blocked by a disabled/ack/armed config flag
  blocked_before_C43            valid plan + wait, never reached C4.3 (catch-all; true for 100% today
                                 since judge_approve_trade=0 in the audited window)

This is a read-only report tool: no state/ writes, no Coinbase calls, no order
submission of any kind.

Usage:
    python3 tools/analyze_missed_opportunities.py [--hours 72]
"""
from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_JSONL = ROOT / "logs" / "analysis.jsonl"
DEFAULT_OUT_JSON = ROOT / "reports" / "audits" / "missed-opportunities-72h-latest.json"
DEFAULT_OUT_MD = ROOT / "reports" / "audits" / "missed-opportunities-72h-latest.md"

HORIZONS_HOURS = {"1h": 1, "4h": 4, "12h": 12, "24h": 24, "72h": 72}


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


def _classify_blocker(judge: dict, market: dict) -> str:
    reasons = judge.get("judge_reasons") or judge.get("reasons") or []
    text = " ".join(str(r) for r in reasons).lower()
    trigger_text = str(judge.get("trigger_wait_reason") or "").lower()
    full_text = f"{text} {trigger_text}"

    spread_pct = market.get("spread_pct")
    max_spread = market.get("max_spread_pct")
    try:
        if spread_pct is not None and max_spread is not None and float(spread_pct) > float(max_spread):
            return "blocked_by_spread"
    except (TypeError, ValueError):
        pass

    if "reward-to-fee" in full_text or "reward_to_fee" in full_text or "reward/fee" in full_text:
        return "blocked_by_reward_fee"
    if "reward-to-risk" in full_text or "reward_to_risk" in full_text or "reward/risk" in full_text:
        return "blocked_by_reward_risk"
    if "cost budget" in full_text or "cost_budget" in full_text or "llm cost" in full_text:
        return "blocked_by_cost_budget"
    if any(k in full_text for k in (
        "not armed", "submit_ack", "runtime_ack", "not enabled", "trading_disabled",
        "cancel_only", "feature disabled", "flag disabled",
    )):
        return "blocked_by_config_live_flag"
    if any(k in full_text for k in (
        "trigger", "breakout confirmation", "1h close above", "1h close below",
        "acceptance", "retest", "confirmed close", "do_not_chase", "do-not-chase",
        "no-chase", "confirmation zone",
    )):
        return "blocked_by_trigger_confirmation"
    if full_text.strip():
        return "blocked_by_judge"
    return "blocked_before_C43"


def stream_compact(hours_lookback: float, hours_forward: float):
    """One pass, extracting only the fields this tool needs. hours_forward extends
    the read window past `hours_lookback` so forward-return lookups near the edge
    of the labeling window still have real (not synthetic) future prices."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_lookback + hours_forward)
    if not ANALYSIS_JSONL.exists():
        return []
    out = []
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
            fp = r.get("feature_pack") or {}
            market = fp.get("market") or {}
            judge = r.get("judge") or {}
            trade_plan = r.get("trade_plan") or {}
            entry_gate = r.get("entry_gate") or {}
            mid = market.get("mid_price")
            try:
                mid_f = float(mid) if mid is not None else None
            except (TypeError, ValueError):
                mid_f = None
            out.append({
                "ticker": r.get("ticker"),
                "ts": r.get("generated_at"),
                "ts_dt": ts,
                "mid_price": mid_f,
                "spread_pct": market.get("spread_pct"),
                "max_spread_pct": _g(fp, "risk_context") and None,
                "entry_gate_decision": entry_gate.get("decision"),
                "plan_action": trade_plan.get("plan_action"),
                "plan_valid": trade_plan.get("valid_trade_plan"),
                "plan_side": trade_plan.get("side"),
                "setup_type": judge.get("setup_type") or trade_plan.get("setup_type"),
                "judge_decision": judge.get("decision"),
                "judge_reasons": (judge.get("judge_reasons") or judge.get("reasons") or [])[:6],
                "trigger_wait_reason": judge.get("trigger_wait_reason"),
                "objective_score": judge.get("objective_score"),
            })
            del r, fp, market
    out.sort(key=lambda x: (x["ticker"], x["ts_dt"]))
    return out


def build_price_index(records: list[dict]) -> dict[str, tuple[list[datetime], list[float]]]:
    by_ticker: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for r in records:
        if r["mid_price"] is not None:
            by_ticker[r["ticker"]].append((r["ts_dt"], r["mid_price"]))
    index = {}
    for t, series in by_ticker.items():
        series.sort(key=lambda x: x[0])
        index[t] = ([s[0] for s in series], [s[1] for s in series])
    return index


def forward_price(index, ticker: str, at: datetime, hours: float) -> float | None:
    times, prices = index.get(ticker, ([], []))
    if not times:
        return None
    target = at + timedelta(hours=hours)
    i = bisect_left(times, target)
    if i >= len(times):
        return None
    return prices[i]


def excursions(index, ticker: str, at: datetime, hours: float, price0: float) -> tuple[float | None, float | None]:
    """Max favorable / max adverse excursion (pct, signed so favorable>=0>=adverse) within horizon."""
    times, prices = index.get(ticker, ([], []))
    if not times or price0 in (None, 0):
        return None, None
    end = at + timedelta(hours=hours)
    i0 = bisect_left(times, at)
    i1 = bisect_left(times, end)
    window = prices[i0:i1]
    if not window:
        return None, None
    mfe = (max(window) - price0) / price0 * 100
    mae = (min(window) - price0) / price0 * 100
    return round(mfe, 3), round(mae, 3)


def analyze(hours: float) -> dict:
    records = stream_compact(hours, max(HORIZONS_HOURS.values()))
    index = build_price_index(records)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    entries = []
    for r in records:
        if r["ts_dt"] < cutoff:
            continue
        if r["judge_decision"] not in {"wait", "reject"}:
            continue
        if not r["plan_valid"]:
            continue  # Phase 3 focuses on candidates the planner already validated
        ticker = r["ticker"]
        price0 = r["mid_price"]
        if price0 is None:
            continue

        forward = {}
        mfe_mae = {}
        for label, h in HORIZONS_HOURS.items():
            forward[label] = forward_price(index, ticker, r["ts_dt"], h)
            mfe, mae = excursions(index, ticker, r["ts_dt"], h, price0)
            mfe_mae[label] = {"mfe_pct": mfe, "mae_pct": mae}

        mfe_24h = mfe_mae["24h"]["mfe_pct"]
        mae_24h = mfe_mae["24h"]["mae_pct"]

        market = {"spread_pct": r["spread_pct"], "max_spread_pct": 0.006}
        judge_like = {"judge_reasons": r["judge_reasons"], "trigger_wait_reason": r["trigger_wait_reason"]}
        first_blocker = _classify_blocker(judge_like, market)

        if mfe_24h is None:
            label = "insufficient_forward_data"
        elif mfe_24h >= 1.5 and (mae_24h is None or mae_24h > -1.0):
            label = "missed_opportunity"
        elif mfe_24h >= 0.5 and (mae_24h is None or mae_24h > -1.5):
            label = "too_conservative"
        elif mae_24h is not None and mae_24h <= -1.5:
            label = "good_wait"
        else:
            label = "good_wait"

        # was the trigger itself too strict? true when label is missed/too_conservative
        # AND the blocker was specifically a trigger/confirmation requirement.
        trigger_too_strict = label in {"missed_opportunity", "too_conservative"} and first_blocker == "blocked_by_trigger_confirmation"

        recommended_layer = {
            "blocked_by_trigger_confirmation": "small_probe promotion gate (bot/strategy_engine.py:_maybe_promote_wait_to_small_probe) -- fixed 2026-07-02",
            "blocked_by_judge": "final judge prompt / JUDGE_MIN_GATE_CONFIDENCE calibration (bot/prompts.py, bot/config.py)",
            "blocked_by_spread": "MAX_SPREAD_PCT (was not observed to bind in this window)",
            "blocked_by_reward_fee": "PHASE_D2_MIN_REWARD_TO_FEE_RATIO -- N/A, D2 does not run pre-entry (see entry-funnel-72h-latest.md)",
            "blocked_by_reward_risk": "PHASE_D2_MIN_REWARD_TO_RISK_RATIO -- N/A, D2 does not run pre-entry",
            "blocked_by_cost_budget": "LLM cost ledger / budget gate",
            "blocked_by_config_live_flag": "runtime ACK/armed flags in .env",
            "blocked_before_C43": "small_probe promotion gate -- same root cause as blocked_by_trigger_confirmation",
        }.get(first_blocker, "judge")

        entries.append({
            "ticker": ticker,
            "ts": r["ts"],
            "plan_action": r["plan_action"],
            "setup_type": r["setup_type"],
            "price_at_decision": price0,
            "forward_prices": forward,
            "excursions": mfe_mae,
            "objective_score": r["objective_score"],
            "first_blocker": first_blocker,
            "label": label,
            "trigger_rule_too_strict": trigger_too_strict,
            "recommended_layer_to_fix": recommended_layer,
            "judge_top_reason": (r["trigger_wait_reason"] or (r["judge_reasons"][0] if r["judge_reasons"] else ""))[:220],
        })

    label_counts = Counter(e["label"] for e in entries)
    blocker_counts = Counter(e["first_blocker"] for e in entries)
    by_ticker: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        by_ticker[e["ticker"]][e["label"]] += 1

    trigger_too_strict_count = sum(1 for e in entries if e["trigger_rule_too_strict"])

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "total_labeled": len(entries),
        "label_counts": dict(label_counts),
        "first_blocker_counts": dict(blocker_counts),
        "trigger_rule_too_strict_count": trigger_too_strict_count,
        "trigger_rule_too_strict_note": (
            f"{trigger_too_strict_count}/{len(entries)} wait decisions on valid plans were blocked purely "
            "by an unmet trigger/confirmation requirement AND price subsequently moved favorably -- i.e. "
            "the trigger rule itself (not a data problem) was the reason the opportunity was missed."
        ),
        "per_ticker_label_counts": {t: dict(c) for t, c in sorted(by_ticker.items())},
        "entries": entries,
    }


def write_md(result: dict, path: Path) -> None:
    lines = [
        "# Missed Opportunity Audit (72h, realized forward returns)",
        f"Generated: {result['generated_at']}  ",
        f"Window: last {result['window_hours']}h",
        f"Total wait/reject decisions on VALID plans labeled: {result['total_labeled']}",
        "",
        "## Label distribution",
        "| Label | Count |",
        "|---|---|",
    ]
    for label, count in sorted(result["label_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {label} | {count} |")
    lines += [
        "",
        "## First-blocker distribution",
        "| Blocker | Count |",
        "|---|---|",
    ]
    for b, count in sorted(result["first_blocker_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {b} | {count} |")
    lines += [
        "",
        f"## Was the trigger rule itself too strict?",
        result["trigger_rule_too_strict_note"],
        "",
        "## Per-ticker label counts",
        "| Ticker | " + " | ".join(sorted(result["label_counts"].keys())) + " |",
        "|---|" + "---|" * len(result["label_counts"]),
    ]
    label_keys = sorted(result["label_counts"].keys())
    for t, counts in result["per_ticker_label_counts"].items():
        row = " | ".join(str(counts.get(k, 0)) for k in label_keys)
        lines.append(f"| {t} | {row} |")

    lines += ["", "## Missed opportunities / too-conservative examples (up to 20)", ""]
    interesting = [e for e in result["entries"] if e["label"] in {"missed_opportunity", "too_conservative"}]
    interesting.sort(key=lambda e: -(e["excursions"]["24h"]["mfe_pct"] or 0))
    for e in interesting[:20]:
        ex = e["excursions"]["24h"]
        lines.append(
            f"- **{e['ticker']}** {e['ts']} | {e['plan_action']} ({e['setup_type']}) | "
            f"price={e['price_at_decision']} | 24h MFE={ex['mfe_pct']}% MAE={ex['mae_pct']}% | "
            f"label={e['label']} | blocker={e['first_blocker']} | fix={e['recommended_layer_to_fix']} | "
            f"reason: {e['judge_top_reason']}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--out", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    print(f"Labeling wait/reject decisions over last {args.hours}h against realized forward prices...")
    result = analyze(args.hours)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"JSON written: {out_path}")

    md_path = Path(args.md)
    write_md(result, md_path)
    print(f"Markdown written: {md_path}")

    print(f"\nLabeled {result['total_labeled']} decisions: {result['label_counts']}")
    print(result["trigger_rule_too_strict_note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
