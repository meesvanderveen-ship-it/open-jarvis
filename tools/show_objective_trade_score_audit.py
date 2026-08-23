#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.objective_trade_score import audit_recent_scores

DEFAULT_JSON = Path("reports/audits/objective-trade-score-audit-latest.json")
DEFAULT_MD = Path("reports/audits/objective-trade-score-audit-latest.md")


def _load_rows(root: Path, limit: int) -> list[dict]:
    path = root / "logs/analysis.jsonl"
    if not path.exists():
        return []
    tail: deque[str] = deque(maxlen=max(1, int(limit)))
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            tail.append(line)
    rows: list[dict] = []
    for line in tail:
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _md(report: dict) -> str:
    lines = ["# Objective Trade Score Audit", "", "Report-only score; it cannot authorize live orders.", ""]
    for row in report["scores"]:
        lines.append(f"- {row.get('ticker')}: score={row['objective_score']} grade={row['grade']} action={row['recommended_action']}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit recent decisions with objective report-only score.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = audit_recent_scores(_load_rows(Path(args.root), args.limit))
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "rows": report["rows"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
