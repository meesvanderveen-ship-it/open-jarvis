#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.decision_outcome_tracker import DecisionOutcomeStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show read-only decision outcome learning analytics.")
    parser.add_argument("--path", default="state/decision_outcomes.json", help="Path to decision outcome state JSON")
    parser.add_argument("--log-path", default="logs/decision_outcomes.jsonl", help="Path to decision outcome JSONL log")
    parser.add_argument("--ticker", default=None, help="Optional ticker filter, e.g. ADA-USDC")
    parser.add_argument("--limit", type=int, default=100, help="Max resolved records to include")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--write-report", default=None, help="Write JSON report to this path")
    args = parser.parse_args()

    store = DecisionOutcomeStore(path=args.path, log_path=args.log_path)
    summary = store.summary(ticker=args.ticker, limit=args.limit)

    if args.write_report:
        store.write_report(args.write_report, ticker=args.ticker, limit=args.limit)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    overall = summary.get("overall", {})
    print("Decision outcome learning overview")
    print("==================================")
    print(f"source_path: {args.path}")
    print(f"ticker:      {args.ticker or 'ALL'}")
    print(f"count:       {summary.get('count', 0)}")
    print(f"outcomes:    {overall.get('outcome_counts', {})}")
    print(f"safety:      {summary.get('learning_policy')}")
    print()

    for title, key in [
        ("MISSED OPPORTUNITIES — soft observation only", "missed_opportunities"),
        ("FALSE POSITIVE PLANS — review thesis quality", "false_positive_plans"),
        ("CORRECT AVOIDS — avoid overfitting", "correct_avoids"),
    ]:
        rows = summary.get(key) or []
        print(f"{title} ({len(rows)})")
        print("-" * len(f"{title} ({len(rows)})"))
        if not rows:
            print("geen records")
        for row in rows:
            print(
                f"- {row.get('ticker')} {row.get('horizon_hours')}h "
                f"{row.get('decision_category')} -> {row.get('outcome_label')} "
                f"price_change={row.get('price_change_pct')} mfe={row.get('max_favorable_pct')} mae={row.get('max_adverse_pct')}"
            )
        print()

    if args.write_report:
        print(f"Wrote report: {args.write_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
