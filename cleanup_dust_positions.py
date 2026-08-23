#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from bot.strategy_engine import StrategyEngine


def main() -> int:
    engine = StrategyEngine()
    inventory_sync = engine._sync_exchange_inventory_positions()
    cleanup = engine._cleanup_unexecutable_open_positions()
    payload = {
        "inventory_sync": inventory_sync,
        "cleanup": cleanup,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
