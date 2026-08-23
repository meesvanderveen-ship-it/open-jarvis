#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from tools.build_full_workflow_integrity_audit import build_backlog

DEFAULT_JSON = Path("reports/audits/trade-workflow-hardening-backlog-latest.json")
DEFAULT_MD = Path("reports/audits/trade-workflow-hardening-backlog-latest.md")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build P0/P1/P2/P3 trade workflow backlog.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    items = build_backlog(args.root)
    report = {"items": items, "read_only": True, "coinbase_call_attempted_by_tool": False}
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, "\n".join(["# Trade Workflow Hardening Backlog", ""] + [f"- `{x['priority']}` {x['title']}: {x['risk']}" for x in items]) + "\n")
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "items": len(items)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
