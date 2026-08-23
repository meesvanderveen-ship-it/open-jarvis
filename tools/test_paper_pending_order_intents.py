#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.pending_order_intents import (
    PendingOrderIntentStore,
    build_pending_intent_from_execution_plan,
    build_watchlist_intent_from_analysis,
)


def _feature_pack(price="100"):
    return {
        "market": {"mid_price": price, "price": price},
        "structure": {"nearest_support": "98", "nearest_resistance": "105", "range_low": "98", "range_high": "105"},
        "orderbook_context": {"best_bid": "99", "best_ask": "101", "mid_price": price},
    }


def _analysis():
    return {
        "ticker": "TEST-B6-USDC",
        "feature_pack": _feature_pack("100"),
        "entry_gate": {"decision": "watch", "confidence": 62, "setup_type": "reclaim", "reasons": ["diagnostic watch setup"]},
        "judge": {"decision": "wait", "confidence": 62, "reasons": ["diagnostic wait"]},
        "trade_plan": {
            "plan_action": "prepare_reclaim",
            "entry_zone_low": "99",
            "entry_zone_high": "101",
            "trigger_price": "101",
            "stop_loss": "97",
            "do_not_chase_above": "106",
            "confidence": 64,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose voor fase B.6 paper pending order-intents.")
    parser.add_argument("--project-state", action="store_true")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()

    if args.project_state:
        if not args.confirm_write:
            print("Gebruik --confirm-write om bewust in project-state te schrijven.")
            return 2
        state_path = Path("state/pending_order_intents.json")
        log_path = Path("logs/pending_order_intents.jsonl")
        tmpdir = None
        mode = "project_state_confirmed_no_coinbase_calls"
    else:
        tmpdir = tempfile.TemporaryDirectory(prefix="phase_b6_pending_intents_")
        state_path = Path(tmpdir.name) / "pending_order_intents.json"
        log_path = Path(tmpdir.name) / "pending_order_intents.jsonl"
        mode = "temporary_diagnostic_no_coinbase_calls"

    store = PendingOrderIntentStore(path=state_path, log_path=log_path, max_records=50, enabled=True)
    analysis = _analysis()
    execution_plan = {
        "execution_action": "pending_plan_only",
        "data_sufficiency": "sufficient",
        "execution_quality_score": 72,
        "expiry_hours": 6,
        "reason": "phase_b6_diagnostic_pending_plan_only",
        "cancel_if": ["price breaks invalidation"],
        "replace_if": ["fresh reclaim trigger changes"],
    }

    pending = build_pending_intent_from_execution_plan(
        cfg=cfg,
        ticker="TEST-B6-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        feature_pack=analysis["feature_pack"],
        cycle_source="phase_b6_diagnostic",
    )
    watch = build_watchlist_intent_from_analysis(
        cfg=cfg,
        ticker="TEST-B6B-USDC",
        analysis={**analysis, "ticker": "TEST-B6B-USDC"},
        feature_pack=_feature_pack("100"),
        cycle_source="phase_b6_diagnostic",
    )

    stored_pending = store.store_intent({**pending, "intent_id": "paper-diagnostic-b6-pending"}) if pending else None
    stored_watch = store.store_intent({**watch, "intent_id": "paper-diagnostic-b6-watch", "ticker": "TEST-B6B-USDC"}) if watch else None

    review_waiting = store.evaluate_intents({"TEST-B6-USDC": _feature_pack("98.5"), "TEST-B6B-USDC": _feature_pack("98.5")})
    review_trigger = store.evaluate_intents({"TEST-B6-USDC": _feature_pack("100"), "TEST-B6B-USDC": _feature_pack("98")})

    result = {
        "mode": mode,
        "state_path": str(state_path),
        "log_path": str(log_path),
        "stored_pending": bool(stored_pending),
        "stored_watch": bool(stored_watch),
        "review_waiting_reviewed": review_waiting.get("reviewed"),
        "review_trigger_reviewed": review_trigger.get("reviewed"),
        "summary": store.summary(),
    }
    print("Phase-B.6 paper pending order-intents diagnose")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if tmpdir is not None:
        tmpdir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
