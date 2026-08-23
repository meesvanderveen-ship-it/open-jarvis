#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.setup_pattern_library import build_setup_pattern_status

DEFAULT_JSON = Path("reports/audits/setup-pattern-and-parameter-gap-analysis-latest.json")
DEFAULT_MD = Path("reports/audits/setup-pattern-and-parameter-gap-analysis-latest.md")


def _parameter_matrix() -> list[dict[str, object]]:
    rows = [
        ("ATR", "volatility", True, True, True, True, False, False, False, "Keep in stop/target sanity and add percentile.", "P2"),
        ("ATR percentile", "volatility", False, False, False, False, False, False, True, "Add rolling percentile to feature_pack for regime-aware sizing.", "P1"),
        ("volatility regime", "volatility", True, True, True, False, True, True, False, "Promote to numeric deterministic context.", "P2"),
        ("candle body/wick ratio", "momentum", False, False, False, False, False, False, True, "Add report-only candle-shape features before prompt use.", "P2"),
        ("breakout distance", "momentum", True, True, True, True, False, False, False, "Keep in orderbook preview and expose in objective score.", "P2"),
        ("retest distance", "momentum", True, True, True, True, False, False, False, "Keep; add watch-memory ranking.", "P2"),
        ("trend slope", "trend", True, True, True, False, True, False, False, "Use explicitly in objective score.", "P2"),
        ("EMA 8/21/50/200", "trend", False, False, False, False, False, False, True, "Add EMA 8/21 while keeping existing EMA20/50/200.", "P2"),
        ("VWAP", "trend", False, False, False, False, False, False, True, "Add VWAP reclaim as report-only setup first.", "P2"),
        ("RSI", "momentum", True, True, True, True, True, True, False, "Keep; add divergence POC if useful.", "P3"),
        ("MACD", "momentum", False, False, False, False, False, False, True, "Add only if backtest/audit shows value.", "P3"),
        ("Bollinger/Keltner squeeze", "volatility", True, True, True, False, True, False, False, "Bollinger squeeze exists; Keltner missing.", "P2"),
        ("support/resistance distance", "risk", True, True, True, True, False, False, False, "Keep and require in judge/orderbook context.", "P1"),
        ("volume z-score", "volume", False, False, False, False, False, False, True, "Add z-score beside volume_vs_avg.", "P2"),
        ("orderbook imbalance", "orderbook", True, True, False, True, False, False, True, "Inject summarized imbalance into planner/judge.", "P1"),
        ("bid/ask depth", "orderbook", True, True, True, True, False, False, False, "Keep; add stale/depth thresholds in audit.", "P1"),
        ("spread", "orderbook", True, True, True, True, False, False, False, "Keep deterministic gate.", "P0"),
        ("estimated slippage", "execution", False, False, False, False, False, False, True, "Add depth-based estimate to feature_pack.", "P1"),
        ("maker/taker fees", "execution", True, True, False, True, False, False, True, "Promote fee context to judge and objective score.", "P1"),
        ("reward-to-fee", "risk", True, True, False, True, False, False, True, "Expose numeric ratio to judge, not just orderbook preview.", "P1"),
        ("reward-to-risk", "risk", True, True, False, True, False, False, True, "Expose numeric ratio to judge.", "P1"),
        ("product precision", "execution", True, True, False, True, False, False, True, "P0: inject into decision context and keep submitter fail-closed.", "P0"),
        ("min order size", "execution", True, True, False, True, False, False, True, "P0: inject into decision context and recent rejection learning.", "P0"),
        ("quote-to-base conversion", "execution", True, True, False, True, False, False, True, "Keep in submitter; add audit row in context quality.", "P0"),
    ]
    keys = [
        "parameter", "category", "currently_computed", "currently_logged", "used_in_prompt",
        "used_in_deterministic_gate", "used_in_backtest", "used_in_learning",
        "missing_from_agent_context", "recommended_use", "priority",
    ]
    return [dict(zip(keys, row)) for row in rows]


def build_report() -> dict[str, object]:
    setup = build_setup_pattern_status()
    return {
        **setup,
        "parameter_matrix": _parameter_matrix(),
        "top_gaps": [
            "P0 product precision/min order/reject reason context is available downstream but not consistently in planner/judge prompt context.",
            "P1 opportunity_memory POC is not the primary trigger-promotion route; pending_trade_plans are integrated, opportunity_memory remains parallel.",
            "P1 reward-to-fee/reward-to-risk are deterministic in orderbook preview but not normalized into final judge input.",
            "P2 missing VWAP, EMA 8/21, MACD, Keltner squeeze and volume z-score feature pack fields.",
        ],
    }


def _md(report: dict[str, object]) -> str:
    lines = ["# Setup Pattern And Parameter Gap Analysis", "", "Report-only; no live order authority.", "", "## Setup Patterns"]
    for row in report["matrix"]:  # type: ignore[index]
        lines.append(f"- `{row['priority']}` {row['setup_pattern']}: supported={row['currently_supported']} missing={', '.join(row['missing']) or 'none'}")
    lines.extend(["", "## Parameters"])
    for row in report["parameter_matrix"]:  # type: ignore[index]
        lines.append(f"- `{row['priority']}` {row['parameter']}: computed={row['currently_computed']} prompt={row['used_in_prompt']} gate={row['used_in_deterministic_gate']}")
    lines.extend(["", "## Top Gaps"])
    lines.extend(f"- {gap}" for gap in report["top_gaps"])  # type: ignore[index]
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show report-only setup pattern status.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report()
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    payload = {"json_out": args.json_out, "md_out": args.md_out, "patterns": report["summary"]["patterns_total"]}
    print(json.dumps(payload if args.json else payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
