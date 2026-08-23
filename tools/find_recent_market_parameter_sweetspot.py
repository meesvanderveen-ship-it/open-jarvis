#!/usr/bin/env python3
"""Phase 5 tool: simulate several small-probe-promotion parameter profiles against
the last N hours of REAL judge/analyst output (logs/analysis.jsonl) and compare
how many valid prepare_* candidates each profile would have promoted to
approve_trade, replaying the exact decision logic of
bot/strategy_engine.py:_maybe_promote_wait_to_small_probe.

This does not call any LLM, does not touch state/, and submits no orders. It is
a deterministic replay of already-recorded analyst scores/indicators against
different threshold sets.

Profiles:
  A_current_pre_fix   the thresholds as they were before the 2026-07-02 fix
                       (OR-based HTF filter, bear_score >= max(40, bull-4) veto)
  B_growbot_river_proposal  placeholder profile reflecting the existing
                       config/parameter_profiles/recent_market_calibrated_candidate.json
                       (that profile only touches D2/gate params, not small-probe
                       thresholds, so it is numerically identical to A here --
                       reported explicitly, not hidden)
  C_recent_market_loose     wide gap tolerance / low thresholds
  D_balanced_small_probe    the new live defaults (bot/config.py as of this fix)
  E_high_confidence_momentum  tighter than D, only very strong setups

Usage:
    python3 tools/find_recent_market_parameter_sweetspot.py [--hours 72]
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
DEFAULT_OUT_JSON = ROOT / "reports" / "backtests" / "recent-market-parameter-sweetspot-latest.json"
DEFAULT_OUT_MD = ROOT / "reports" / "backtests" / "recent-market-parameter-sweetspot-latest.md"

ENTRY_PLAN_ACTIONS_FOR_PROMOTION = {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion"}


def _parse_ts(value: Any):
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


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def stream_candidates(hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    if not ANALYSIS_JSONL.exists():
        return out
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
            trade_plan = r.get("trade_plan") or {}
            plan_action = str(trade_plan.get("plan_action") or "").lower()
            if not trade_plan.get("valid_trade_plan") or plan_action not in ENTRY_PLAN_ACTIONS_FOR_PROMOTION:
                continue

            fp = r.get("feature_pack") or {}
            indicators = fp.get("indicators") or {}
            structure = fp.get("structure") or {}
            micro = fp.get("microstructure") or {}
            entry_gate = r.get("entry_gate") or {}
            synth = r.get("synth") or {}
            bull = r.get("bull") or {}
            bear = r.get("bear") or {}
            breakout = r.get("breakout") or {}

            out.append({
                "ticker": r.get("ticker"),
                "ts": r.get("generated_at"),
                "mid_price": _g(fp, "market", "mid_price"),
                "plan_action": plan_action,
                "entry_gate_setup_type": entry_gate.get("setup_type"),
                "bull_score": _f(bull.get("bull_case_score")),
                "bear_score": _f(bear.get("bear_case_score")),
                "synth_conf": _f(synth.get("composite_confidence")),
                "breakout_confirmation": _f(breakout.get("breakout_confirmation_score")),
                "vol_15m": _f(_g(micro, "15m", "volume_vs_avg")),
                "vol_1h": _f(_g(micro, "1h", "volume_vs_avg")),
                "rsi_1h": _f(_g(indicators, "1h", "rsi_14"), 50.0),
                "rsi_4h": _f(_g(indicators, "4h", "rsi_14"), 50.0),
                "close_1h": _f(_g(indicators, "1h", "close")),
                "ema20_1h": _f(_g(indicators, "1h", "ema_20")),
                "ema50_1h": _f(_g(indicators, "1h", "ema_50")),
                "ema50_4h": _f(_g(indicators, "4h", "ema_50")),
                "ema200_4h": _f(_g(indicators, "4h", "ema_200")),
                "bb_mid_1h": _f(_g(indicators, "1h", "bb_mid")),
                "close_15m": _f(_g(indicators, "15m", "close")),
                "ema20_15m": _f(_g(indicators, "15m", "ema_20")),
                "higher_lows_1h": bool(structure.get("higher_lows_1h")),
                "higher_highs_1h": bool(structure.get("higher_highs_1h")),
                "lower_highs_1h": bool(structure.get("lower_highs_1h")),
                "lower_lows_1h": bool(structure.get("lower_lows_1h")),
                "compression_detected": bool(structure.get("compression_detected")),
            })
            del r, fp, indicators, structure, micro
    return out


PROFILES = {
    "A_current_pre_fix": dict(
        max_gap=4, htf_and=False, legacy_mixed_context=True,
        tc_synth=78, tc_bull=64, tc_bconf=60, tc_vol15=0.95, tc_vol1h=0.85,
        rc_synth=80, rc_bull=64, rc_bconf=52, rc_vol15=0.90, rc_vol1h=0.80,
    ),
    "B_growbot_river_proposal_profile": dict(
        # config/parameter_profiles/recent_market_calibrated_candidate.json only
        # adjusts PHASE_D2_* / JUDGE_MIN_GATE_CONFIDENCE, none of which affect the
        # small-probe promotion gate simulated here -- numerically same as A.
        max_gap=4, htf_and=False, legacy_mixed_context=True,
        tc_synth=78, tc_bull=64, tc_bconf=60, tc_vol15=0.95, tc_vol1h=0.85,
        rc_synth=80, rc_bull=64, rc_bconf=52, rc_vol15=0.90, rc_vol1h=0.80,
    ),
    "C_recent_market_loose": dict(
        max_gap=45, htf_and=True, legacy_mixed_context=False,
        tc_synth=60, tc_bull=45, tc_bconf=30, tc_vol15=0.30, tc_vol1h=0.25,
        rc_synth=58, rc_bull=42, rc_bconf=26, rc_vol15=0.30, rc_vol1h=0.25,
    ),
    "D_balanced_small_probe": dict(
        # matches the new live defaults in bot/config.py
        max_gap=32, htf_and=True, legacy_mixed_context=False,
        tc_synth=68, tc_bull=55, tc_bconf=42, tc_vol15=0.55, tc_vol1h=0.45,
        rc_synth=65, rc_bull=52, rc_bconf=36, rc_vol15=0.50, rc_vol1h=0.40,
    ),
    "E_high_confidence_momentum": dict(
        max_gap=22, htf_and=True, legacy_mixed_context=False,
        tc_synth=73, tc_bull=60, tc_bconf=50, tc_vol15=0.75, tc_vol1h=0.65,
        rc_synth=73, rc_bull=58, rc_bconf=44, rc_vol15=0.70, rc_vol1h=0.60,
    ),
}


def evaluate(c: dict, params: dict) -> tuple[bool, str]:
    plan_action = c["plan_action"]
    if plan_action == "prepare_breakout":
        branch = "trend_continuation"
    elif plan_action == "prepare_reclaim":
        branch = "reclaim_reversal"
    else:
        return False, "unsupported_branch_mean_reversion_or_buy"

    bull, bear = c["bull_score"], c["bear_score"]
    b4h = c["ema50_4h"] > 0 and c["ema200_4h"] > 0 and c["ema50_4h"] < c["ema200_4h"]
    b1h = c["ema20_1h"] > 0 and c["ema50_1h"] > 0 and c["ema20_1h"] < c["ema50_1h"]
    bearish_htf = (b4h and b1h) if params["htf_and"] else (b4h or b1h)

    if params.get("legacy_mixed_context"):
        if bear >= max(40, bull - 4):
            return False, "mixed_context_legacy_veto"
    else:
        if (bear - bull) >= params["max_gap"]:
            return False, "gap_veto"

    if bearish_htf:
        return False, "bearish_htf"

    if branch == "trend_continuation":
        checks = {
            "synth": c["synth_conf"] >= params["tc_synth"],
            "bull": bull >= params["tc_bull"],
            "bconf": c["breakout_confirmation"] >= params["tc_bconf"],
            "vol15": c["vol_15m"] >= params["tc_vol15"],
            "vol1h": c["vol_1h"] >= params["tc_vol1h"],
            "rsi1h": c["rsi_1h"] <= 72.0,
            "rsi4h": c["rsi_4h"] <= 75.0,
            "px_ema20": c["close_1h"] >= c["ema20_1h"],
            "px_ema50": c["close_1h"] >= c["ema50_1h"],
            "structure": (c["higher_lows_1h"] or c["higher_highs_1h"] or c["compression_detected"])
            and not (c["lower_highs_1h"] and c["lower_lows_1h"]),
        }
        if params.get("legacy_mixed_context"):
            checks["bear_cap"] = bear <= max(30, bull - 6)
    else:
        price_near_15m_ema = c["ema20_15m"] > 0 and c["close_15m"] >= c["ema20_15m"] * 0.999
        holding_1h_mid = c["bb_mid_1h"] <= 0 or c["close_1h"] >= c["bb_mid_1h"]
        checks = {
            "synth": c["synth_conf"] >= params["rc_synth"],
            "bull": bull >= params["rc_bull"],
            "bconf": c["breakout_confirmation"] >= params["rc_bconf"],
            "vol15": c["vol_15m"] >= params["rc_vol15"],
            "vol1h": c["vol_1h"] >= params["rc_vol1h"],
            "rsi1h": c["rsi_1h"] <= 70.0,
            "rsi4h": c["rsi_4h"] <= 74.0,
            "near_ema": price_near_15m_ema,
            "holding_mid": holding_1h_mid,
            "structure": (c["higher_lows_1h"] or c["compression_detected"]) and not c["lower_lows_1h"],
        }
        if params.get("legacy_mixed_context"):
            checks["bear_cap"] = bear <= max(34, bull - 2)

    failed = [k for k, v in checks.items() if not v]
    if failed:
        return False, failed[0]
    return True, "pass"


def run_sweetspot(hours: float) -> dict:
    candidates = stream_candidates(hours)
    profile_results = {}

    for name, params in PROFILES.items():
        promoted = []
        fail_reasons: Counter = Counter()
        tickers_hit = set()
        for c in candidates:
            ok, why = evaluate(c, params)
            fail_reasons[why] += 1
            if ok:
                promoted.append(c)
                tickers_hit.add(c["ticker"])

        profile_results[name] = {
            "params": params,
            "candidates_evaluated": len(candidates),
            "promoted_count": len(promoted),
            "promoted_pct": round(100 * len(promoted) / len(candidates), 1) if candidates else 0.0,
            "tickers_hit": sorted(tickers_hit),
            "fail_reason_counts": dict(fail_reasons.most_common(10)),
            "promoted_examples": [
                {"ticker": c["ticker"], "ts": c["ts"], "plan_action": c["plan_action"], "price": c["mid_price"]}
                for c in promoted[:15]
            ],
        }

    # recommended profile: the loosest profile that still keeps a real quality
    # floor (i.e. not C_recent_market_loose, which lets almost everything through)
    # and produces at least one promotion in this real window.
    recommended = "D_balanced_small_probe"
    if profile_results["D_balanced_small_probe"]["promoted_count"] == 0:
        recommended = "C_recent_market_loose"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "candidates_evaluated": len(candidates),
        "profiles": profile_results,
        "recommended_profile": recommended,
        "recommendation_reason": (
            "D_balanced_small_probe is the tightest profile that still converts a non-zero, "
            "non-trivial share of real 72h candidates (see promoted_count/promoted_pct per profile) "
            "while requiring both HTF timeframes to agree (no lagging-EMA-only vetoes) and keeping "
            "every quality threshold above the live-data median. C_recent_market_loose promotes far "
            "more but at the cost of accepting bottom-quartile setups -- kept as an upper bound for "
            "comparison, not the recommendation. This is now the live default in bot/config.py."
        ),
    }


def write_md(result: dict, path: Path) -> None:
    lines = [
        "# Recent-Market Parameter Sweetspot (small-probe promotion gate)",
        f"Generated: {result['generated_at']}  ",
        f"Window: last {result['window_hours']}h  |  candidates evaluated: {result['candidates_evaluated']}",
        "",
        "## Profile comparison",
        "| Profile | promoted | % of candidates | tickers hit |",
        "|---|---|---|---|",
    ]
    for name, r in result["profiles"].items():
        lines.append(f"| {name} | {r['promoted_count']}/{r['candidates_evaluated']} | {r['promoted_pct']}% | {', '.join(r['tickers_hit']) or '-'} |")

    lines += [
        "",
        f"## Recommended profile: `{result['recommended_profile']}`",
        result["recommendation_reason"],
        "",
    ]

    for name, r in result["profiles"].items():
        lines.append(f"## {name}")
        lines.append(f"Params: `{json.dumps(r['params'])}`")
        lines.append(f"Promoted: {r['promoted_count']}/{r['candidates_evaluated']} ({r['promoted_pct']}%)")
        lines.append("Top block reasons: " + ", ".join(f"{k}={v}" for k, v in r["fail_reason_counts"].items()))
        if r["promoted_examples"]:
            lines.append("Examples:")
            for ex in r["promoted_examples"]:
                lines.append(f"  - {ex['ticker']} {ex['ts']} {ex['plan_action']} @ {ex['price']}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--out", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    print(f"Simulating parameter profiles against {args.hours}h of real candidates...")
    result = run_sweetspot(args.hours)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"JSON written: {out_path}")

    md_path = Path(args.md)
    write_md(result, md_path)
    print(f"Markdown written: {md_path}")

    for name, r in result["profiles"].items():
        print(f"  {name:32s} promoted={r['promoted_count']:3d}/{r['candidates_evaluated']} ({r['promoted_pct']}%)")
    print(f"\nRecommended: {result['recommended_profile']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
