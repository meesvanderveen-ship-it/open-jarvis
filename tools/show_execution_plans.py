#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _read_tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon recente read-only execution planner adviezen.")
    parser.add_argument("--path", default="logs/execution_plans.jsonl")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="Print ruwe JSON in plaats van compacte tabel")
    args = parser.parse_args()

    path = Path(args.path)
    rows = _read_tail_jsonl(path, max(1, args.limit))
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print(f"Geen execution plans gevonden in {path}")
        return 0

    print(f"Laatste {len(rows)} execution planner adviezen uit {path}:\n")
    header = f"{'tijd':25} {'ticker':12} {'action':28} {'data':13} {'score':5} {'expiry':6} reden"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{str(row.get('generated_at',''))[:25]:25} "
            f"{str(row.get('ticker',''))[:12]:12} "
            f"{str(row.get('execution_action',''))[:28]:28} "
            f"{str(row.get('data_sufficiency',''))[:13]:13} "
            f"{str(row.get('execution_quality_score',''))[:5]:5} "
            f"{str(row.get('expiry_hours',''))[:6]:6} "
            f"{str(row.get('reason',''))[:100]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
