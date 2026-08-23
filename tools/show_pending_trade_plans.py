#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.pending_trade_plans import PendingTradePlanStore  # noqa: E402


def _short(value: Any, max_len: int = 72) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _print_section(title: str, rows: Iterable[Dict[str, Any]], *, limit: int) -> None:
    rows = list(rows)
    print(f"\n{title} ({len(rows)})")
    print("-" * max(12, len(title) + 4))
    if not rows:
        print("geen records")
        return
    for row in rows[:limit]:
        print(
            f"{row.get('ticker',''):<12} "
            f"{row.get('status',''):<14} "
            f"{_short(row.get('setup_type') or row.get('plan_action'), 22):<22} "
            f"conf={str(row.get('confidence','')):<3} "
            f"exp_h={str(row.get('hours_until_expiry','')):<8} "
            f"reason={_short(row.get('last_evaluation_reason'), 70)}"
        )
        print(
            f"  zone={row.get('entry_zone_low')}..{row.get('entry_zone_high')} "
            f"stop={row.get('stop_loss')} chase={row.get('do_not_chase_above')}"
        )
        if row.get("trigger"):
            print(f"  trigger: {_short(row.get('trigger'), 110)}")
        if row.get("invalidation"):
            print(f"  invalidation: {_short(row.get('invalidation'), 110)}")
        print(f"  plan_id: {row.get('plan_id')}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show pending trade plan observability. Read-only: this script never evaluates triggers, "
            "places orders, calls LLMs, or calls Coinbase."
        )
    )
    parser.add_argument("--path", default="state/pending_trade_plans.json", help="Path to pending_trade_plans.json")
    parser.add_argument("--json", action="store_true", help="Print full JSON summary")
    parser.add_argument("--active-only", action="store_true", help="Hide final statuses such as expired/replaced/cancelled")
    parser.add_argument("--limit", type=int, default=25, help="Maximum rows per section")
    args = parser.parse_args()

    store = PendingTradePlanStore(path=args.path, enabled=True)
    summary = store.observability_summary(include_final=not args.active_only, limit=max(1, args.limit))

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print("Pending trade plans observability")
    print("================================")
    print(f"generated_at: {summary.get('generated_at')}")
    print(f"state_path:    {Path(args.path)}")
    print(f"total:         {summary.get('total_plans')}")
    print(f"trigger_ready: {summary.get('trigger_ready_count')}")
    print(f"active:        {summary.get('active_count')}")
    print(f"final:         {summary.get('final_count')}")
    print(f"status_counts: {summary.get('status_counts')}")
    print(f"ticker_counts: {summary.get('ticker_counts')}")
    print(f"safety:        {summary.get('safety_policy')}")

    _print_section("TRIGGER READY — requires fresh GPT-5.5 judge + risk check", summary.get("actionable_trigger_ready", []), limit=args.limit)
    _print_section("ACTIVE / WAITING", summary.get("active_or_waiting", []), limit=args.limit)
    if not args.active_only:
        _print_section("FINAL RECENT", summary.get("final_recent", []), limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
