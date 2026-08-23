#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon paper execution-outcome records voor de Coinbase bot.")
    parser.add_argument("--path", default="logs/execution_outcomes.jsonl")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--exclude-diagnostics", action="store_true", help="Verberg TEST-/diagnostic records in de output.")
    args = parser.parse_args()

    rows = load_jsonl(Path(args.path))
    if args.exclude_diagnostics:
        rows = [row for row in rows if not str(row.get("ticker") or "").startswith("TEST-") and not str(row.get("paper_order_reason") or "").startswith("phase_b_diagnostic_")]
    rows = rows[-max(1, args.limit):]

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print(f"Geen execution outcomes gevonden in {args.path}")
        return 0

    if args.summary:
        by_label: Dict[str, int] = {}
        by_ticker: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        for row in rows:
            label = str(row.get("primary_label") or "unknown")
            ticker = str(row.get("ticker") or "UNKNOWN")
            by_label[label] = by_label.get(label, 0) + 1
            by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
            source = str(row.get("source") or "unknown")
            by_source[source] = by_source.get(source, 0) + 1
        print("Execution outcome summary")
        print("by_label:", json.dumps(by_label, ensure_ascii=False, sort_keys=True))
        print("by_ticker:", json.dumps(by_ticker, ensure_ascii=False, sort_keys=True))
        print("by_source:", json.dumps(by_source, ensure_ascii=False, sort_keys=True))
        print("allowed_use: soft_context_only")
        print("overfit_warning: paper records only; never change hard risk rails automatically")
        return 0

    print(f"Laatste {len(rows)} execution outcomes uit {args.path}:\n")
    print(f"{'tijd':25} {'ticker':12} {'side':5} {'status':12} {'label':26} {'confidence':10} {'source':28} reden")
    print("-" * 120)
    for row in rows:
        reason = str(row.get("reason") or "")[:80]
        print(
            f"{str(row.get('generated_at') or '')[:25]:25} "
            f"{str(row.get('ticker') or '')[:12]:12} "
            f"{str(row.get('side') or '')[:5]:5} "
            f"{str(row.get('order_status') or '')[:12]:12} "
            f"{str(row.get('primary_label') or '')[:26]:26} "
            f"{str(row.get('confidence') or '')[:10]:10} "
            f"{str(row.get('source') or '')[:28]:28} "
            f"{reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
