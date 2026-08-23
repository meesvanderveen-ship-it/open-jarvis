#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text

DEFAULT_JSON = Path("reports/research/open-source-bot-feature-comparison-latest.json")
DEFAULT_MD = Path("reports/research/open-source-bot-feature-comparison-latest.md")

SOURCES = [
    {"name": "Freqtrade stoploss docs", "url": "https://www.freqtrade.io/en/stable/stoploss/", "license": "Project license referenced from https://github.com/freqtrade/freqtrade/blob/develop/LICENSE"},
    {"name": "Hummingbot architecture", "url": "https://hummingbot.org/blog/hummingbot-architecture---part-1/", "license": "Project license referenced from https://github.com/hummingbot/hummingbot/blob/master/LICENSE"},
    {"name": "Jesse docs/license", "url": "https://docs.jesse.trade/", "license": "Project license referenced from https://github.com/jesse-ai/jesse/blob/master/LICENSE"},
    {"name": "QuantConnect order events", "url": "https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-events", "license": "Documentation used as pattern reference only"},
]


def _row(feature: str, our_status: str, freqtrade: str, hummingbot: str, jesse: str, literature: str, action: str, priority: str) -> Dict[str, object]:
    return {
        "feature": feature,
        "our_status": our_status,
        "freqtrade_pattern": freqtrade,
        "hummingbot_pattern": hummingbot,
        "jesse_pattern": jesse,
        "literature_pattern": literature,
        "recommended_action": action,
        "priority": priority,
        "copy_code": False,
        "license_notes": "Pattern-level comparison only; no source code copied.",
    }


def build_matrix() -> List[Dict[str, object]]:
    return [
        _row("strategy lifecycle", "present", "bot cycle + strategy callbacks", "clock-driven strategy/connector split", "strategy lifecycle methods", "explicit state transitions", "Document active Mode A/B path.", "P3"),
        _row("backtesting", "partial", "first-class backtesting/hyperopt", "paper/simulation tooling", "first-class backtest", "walk-forward/OOS validation", "Promote D6 backtests into release gate.", "P2"),
        _row("dry-run/live split", "present", "dry-run vs live config", "paper/live connector modes", "backtest/paper/live modes", "environment separation", "Keep live ACK gates and read-only audit tools.", "P0"),
        _row("connector abstraction", "partial", "exchange abstraction", "connector layer is central", "exchange drivers", "adapter + event normalization", "Normalize Coinbase responses and product rules in one adapter.", "P1"),
        _row("order lifecycle", "partial", "order tracking and stoploss intervals", "event-driven connectors", "order state updates", "order events including partial fills", "Strengthen pending-entry cancel/replace reconciliation.", "P1"),
        _row("event-driven order updates", "missing", "polling/exchange updates", "connector event queue", "exchange stream/order events", "OrderEvent callback model", "Add event-normalizer around Coinbase snapshots/fills.", "P1"),
        _row("stoploss", "preview_only", "static/on-exchange/emergency stoploss", "strategy stop controllers", "stop_loss helpers", "stop routes must account for slippage/fill risk", "Mode B apply only after cancel/fill evidence ACK.", "P1"),
        _row("trailing stoploss", "preview_only", "trailing ratchets to highest observed price and can use offset", "strategy controller pattern", "trailing/stop helpers", "never lower stop", "Build D4 cancel-first replace manager.", "P1"),
        _row("partial fills", "partial", "order status aware", "connector fill events", "trade/order events", "partial fill order events", "Add tests for entry partial fill to position sizing and D3 reservation.", "P1"),
        _row("cancel/replace", "partial", "stoploss replacement interval", "hanging/cancel logic", "order update flow", "confirm cancel before replacement", "Keep one replace per thesis and exchange confirmation.", "P1"),
        _row("position accounting", "present", "trade object/accounting", "inventory/order tracker", "position/trade state", "source-of-truth reconciliation", "Continue no local apply without exchange evidence.", "P0"),
        _row("risk sizing", "present", "stake/stoploss config", "budget/checker patterns", "risk per trade", "fixed risk caps", "Keep 50/100 quote caps and max 3 positions.", "P0"),
        _row("precision/min order", "partial", "exchange precision handling", "trading rules per connector", "exchange filters", "round to tick/lot size", "Prove deployed product_rules precision path after restart.", "P0"),
        _row("pair selection/ranking", "present", "pairlists", "market selectors", "routes/pairs", "candidate preselection", "Improve funnel visibility by ticker/setup type.", "P2"),
        _row("hyperparameter optimization", "partial", "hyperopt", "strategy parameter sweeps", "optimization tooling", "avoid overfitting", "Require OOS evidence for profile ACK.", "P2"),
        _row("logs/audits", "present", "logs + UI/API", "logs/status", "logs", "auditability", "Consolidate reports to avoid stale-window confusion.", "P3"),
        _row("dashboards/status", "partial", "FreqUI", "dashboard/client", "web UI", "operator observability", "Keep CLI reports; optional dashboard later.", "P3"),
        _row("strategy memory/watchlist", "partial", "pairlocks/custom state possible", "controller state", "strategy vars", "watchlist with TTL/invalidation", "Wire opportunity memory POC into fresh judge cadence.", "P1"),
        _row("open order reconciliation", "partial", "open order tracking", "connector order tracker", "exchange order updates", "event reconciler", "Add stuck-order report-only detector.", "P1"),
        _row("test fixtures", "present", "rich test ecosystem", "connector mocks", "strategy tests", "fixture-driven order events", "Expand product-rule and rejection fixtures.", "P1"),
    ]


def build_report() -> Dict[str, object]:
    return {
        "sources": SOURCES,
        "matrix": build_matrix(),
        "literature_best_practices": [
            {"source": "Freqtrade stoploss docs", "finding": "Trailing stop follows the highest observed price and can activate only after an offset.", "relevance_to_our_bot": "D4 must never move stop down and should use activation/offset.", "implementation_gap": "Current trailing is preview-only.", "recommended_test_or_code_change": "Add live-disabled D4 ratchet/cancel-first tests."},
            {"source": "Freqtrade stoploss docs", "finding": "Very tight stop-limit orders risk missing fills; emergency path may be needed.", "relevance_to_our_bot": "Mode A near-market limit stop preview can miss in fast markets.", "implementation_gap": "Mode B market/IOC apply remains ACK-gated.", "recommended_test_or_code_change": "Model slippage and stale TP cancel-first path."},
            {"source": "QuantConnect order events docs", "finding": "Order lifecycle should be driven by order status/fill events, including partial fills.", "relevance_to_our_bot": "Coinbase snapshots/fills should normalize into events.", "implementation_gap": "Polling exists; event abstraction is incomplete.", "recommended_test_or_code_change": "Add event normalizer fixtures for partial/fill/cancel/reject."},
            {"source": "Hummingbot architecture", "finding": "Connector abstraction separates strategy decisions from exchange mechanics.", "relevance_to_our_bot": "Coinbase payload precision and response parsing belong in adapter boundary.", "implementation_gap": "Rules can be absent in feature pack; must fail closed.", "recommended_test_or_code_change": "Require product increments for live submit and expose missing rules in audit."},
        ],
        "read_only": True,
        "copy_code": False,
    }


def _md(report: Dict[str, object]) -> str:
    lines = ["# Open Source Bot Feature Comparison", "", "No code copied; pattern comparison only.", "", "## Sources"]
    for source in report["sources"]:  # type: ignore[index]
        lines.append(f"- {source['name']}: {source['url']} ({source['license']})")
    lines.extend(["", "## Matrix"])
    for row in report["matrix"]:  # type: ignore[index]
        lines.append(f"- `{row['priority']}` {row['feature']}: ours `{row['our_status']}`; action: {row['recommended_action']}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build open-source bot feature comparison.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report()
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "features": len(report["matrix"])}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
