#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.pending_order_intents import PendingOrderIntentStore


def _short(value, limit=90):
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon paper pending/watchlist order-intents.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--status", default=None, help="Filter op status, bijvoorbeeld waiting, trigger_ready of needs_fresh_analysis.")
    parser.add_argument("--promotion-ready", action="store_true", help="Toon alleen actuele intents die promotion/fresh-analysis nodig hebben.")
    parser.add_argument("--needs-fresh-analysis", action="store_true", help="Toon alleen actuele intents met status needs_fresh_analysis.")
    parser.add_argument("--path", default="state/pending_order_intents.json")
    args = parser.parse_args()

    store = PendingOrderIntentStore(path=args.path, log_path="logs/pending_order_intents.jsonl")
    intents = store.active_intents() if args.active_only else store.all_intents()
    if args.status:
        wanted_status = str(args.status).strip().lower()
        intents = [item for item in intents if str(item.get("status") or "active").strip().lower() == wanted_status]
    if args.needs_fresh_analysis:
        intents = [item for item in store.active_intents() if str(item.get("status") or "").strip().lower() == "needs_fresh_analysis"]
    if args.promotion_ready:
        intents = [
            item
            for item in store.active_intents()
            if str(item.get("status") or "").strip().lower() in {"trigger_ready", "needs_fresh_analysis"}
        ]
    intents = sorted(intents, key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    summary = store.summary()

    if args.json:
        print(json.dumps({"summary": summary, "intents": intents[: args.limit]}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.summary:
        print("Paper pending order-intents summary")
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not intents:
        print("Geen pending order-intents gevonden.")
        return 0

    print(f"Laatste {min(args.limit, len(intents))} pending order-intents uit {args.path}:")
    print()
    print(f"{'tijd':25} {'ticker':12} {'status':14} {'source':26} {'confidence':10} {'reden'}")
    print("-" * 120)
    for item in intents[: args.limit]:
        print(
            f"{_short(item.get('updated_at') or item.get('created_at'), 25):25} "
            f"{_short(item.get('ticker'), 12):12} "
            f"{_short(item.get('status'), 14):14} "
            f"{_short(item.get('source_kind'), 26):26} "
            f"{_short(item.get('confidence'), 10):10} "
            f"{_short(item.get('reason'), 70)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
