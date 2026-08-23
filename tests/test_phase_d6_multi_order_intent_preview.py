from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_multi_order_intent_preview import (
    build_multi_order_intent_preview_report,
    build_reservation_preview,
    evaluate_order_intent_candidate,
)


def candidate(
    ticker: str = "BTC-USDC",
    *,
    side: str = "BUY",
    setup: str = "reclaim",
    confidence: int = 68,
    price: str = "100",
    best_bid: str = "99.90",
    best_ask: str = "100.00",
    support: str | None = "98",
    resistance: str | None = "108",
    volume_vs_avg: str = "1.20",
    momentum: str = "up",
    pressure: str = "balanced",
    imbalance: str = "0.10",
    spread_pct: str = "0.001",
    do_not_chase: str = "105",
    order_type: str = "limit_maker",
    size_base: str = "0.1",
    min_quote: str = "1",
) -> dict:
    structure = {}
    if support is not None:
        structure["nearest_support"] = support
    if resistance is not None:
        structure["nearest_resistance"] = resistance
    return {
        "ticker": ticker,
        "side": side,
        "setup_family": setup,
        "confidence": confidence,
        "preferred_order_type": order_type,
        "size_base": size_base,
        "feature_pack": {
            "ticker": ticker,
            "market": {
                "mid_price": price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_pct": spread_pct,
                "quote_min_size": min_quote,
            },
            "structure": structure,
            "microstructure": {
                "15m": {"volume_vs_avg": volume_vs_avg, "net_close_direction": momentum},
                "1h": {"volume_vs_avg": volume_vs_avg, "net_close_direction": momentum},
            },
            "orderbook_context": {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid_price": price,
                "bid_ask_spread_pct": spread_pct,
                "book_pressure": pressure,
                "depth_imbalance_top5": imbalance,
                "snapshot_available": True,
            },
            "risk_context": {"available_quote_balance": "250", "min_trade_quote_usdc": min_quote},
        },
        "entry_gate": {"decision": "watch", "confidence": confidence, "setup_type": setup},
        "judge": {"decision": "wait", "side": "NONE", "confidence": confidence},
        "trade_plan": {"do_not_chase_above": do_not_chase},
    }


def empty_reservation(**overrides: object) -> dict:
    base = build_reservation_preview(open_orders_state={"orders": {}}, positions_state={}, quote_available="250")
    base.update(overrides)
    return base


def test_preview_only_report_does_not_submit_or_write_state() -> None:
    report = build_multi_order_intent_preview_report(
        candidates=[candidate()],
        open_orders_state={"orders": {}},
        positions_state={},
        selected_tests_summary={"selected_tests_classification": "OK"},
    )
    assert report["preview_only"] is True
    assert report["live_order_submit_attempted"] is False
    assert report["market_order_submit_attempted"] is False
    assert report["sell_order_submit_attempted"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["total_intents"] == 1
    assert report["preview_ready_intent_count"] == 1
    assert report["near_miss_intent_count"] == 0
    assert report["buy_intents"] == 1
    assert report["intents"][0]["live_submit_eligibility"] is False
    assert report["intents"][0]["hard_blockers"] == []


def test_reservation_caps_open_orders_quote_total_per_ticker_and_cycle() -> None:
    open_orders = {
        "orders": {
            f"o{i}": {"ticker": f"T{i}-USDC", "side": "BUY", "status": "submitted", "remaining_quote": "20"}
            for i in range(5)
        }
    }
    reservation = build_reservation_preview(open_orders_state=open_orders, positions_state={}, quote_available="250")
    assert reservation["open_order_count"] == 5
    assert reservation["reserved_quote_open_buy_orders"] == "100"
    intent = evaluate_order_intent_candidate(candidate("NEW-USDC"), reservation=reservation)
    assert "max_open_order_cap_reached" in intent["blockers"]
    assert "below_product_min_notional" in intent["blockers"]

    one_ticker = build_reservation_preview(
        open_orders_state={"orders": {"o": {"ticker": "BTC-USDC", "side": "BUY", "status": "submitted", "remaining_quote": "10"}}},
        positions_state={},
        quote_available="250",
    )
    blocked = evaluate_order_intent_candidate(candidate("BTC-USDC"), reservation=one_ticker)
    assert "max_one_open_order_per_ticker" in blocked["blockers"]

    selected = evaluate_order_intent_candidate(candidate("ETH-USDC"), reservation=empty_reservation(), selected_so_far=2)
    assert "max_new_orders_per_cycle_reached" in selected["blockers"]


def test_max_order_quote_and_product_min_notional_handling() -> None:
    reservation = empty_reservation(free_quote_available_for_new_buy_intents="50")
    intent = evaluate_order_intent_candidate(candidate(min_quote="25"), reservation=reservation)
    assert intent["proposed_size_quote"] == "20"
    assert "below_product_min_notional" in intent["blockers"]


def test_hard_blockers_still_reject_longshot_chase_book_spread_missing_refs() -> None:
    cases = [
        (candidate(price="106", best_bid="106", best_ask="106.1", do_not_chase="105"), "do_not_chase_violation"),
        (candidate(pressure="ask_heavy", imbalance="-0.50"), "bad_orderbook_pressure"),
        (candidate(spread_pct="0.020"), "wide_spread"),
        (candidate(support=None), "missing_invalidation_reference"),
        (candidate(resistance=None), "missing_target_reference"),
    ]
    for item, expected in cases:
        intent = evaluate_order_intent_candidate(item, reservation=empty_reservation())
        assert expected in intent["blockers"]
        assert intent["status"] == "candidate_rejected"


def test_watch_analyze_wait_are_not_entry_gate_hard_reject_by_default() -> None:
    for decision in ("watch", "analyze", "wait"):
        item = candidate()
        item["entry_gate"]["decision"] = decision
        intent = evaluate_order_intent_candidate(item, reservation=empty_reservation())
        assert "entry_gate_hard_reject" not in intent["hard_blockers"]
        assert intent["status"] == "intent_preview_ready"


def test_explicit_reject_and_blocked_remain_hard_blockers() -> None:
    for decision in ("reject", "blocked"):
        item = candidate()
        item["entry_gate"]["decision"] = decision
        intent = evaluate_order_intent_candidate(item, reservation=empty_reservation())
        assert "entry_gate_hard_reject" in intent["hard_blockers"]
        assert intent["status"] == "candidate_rejected"


def test_known_setup_families_are_recognized() -> None:
    families = [
        "trend_continuation",
        "reclaim_reversal",
        "mean_reversion",
        "breakout",
        "range_reclaim",
        "support_retest",
        "pullback_continuation",
    ]
    for setup in families:
        item = candidate(setup=setup, volume_vs_avg="1.4", momentum="up")
        intent = evaluate_order_intent_candidate(item, reservation=empty_reservation())
        assert intent["setup_family"] == setup
        assert "setup_family_unclear" not in intent["soft_blockers"]


def test_unclear_setup_can_be_near_miss_not_automatic_hard_reject() -> None:
    intent = evaluate_order_intent_candidate(candidate(setup="unclear"), reservation=empty_reservation())
    assert "setup_family_unclear" in intent["soft_blockers"]
    assert "no_recognizable_pattern_setup" not in intent["blockers"]
    assert intent["hard_blockers"] == []
    assert intent["status"] == "near_miss_intent"


def test_unclear_setup_can_infer_from_reason_text() -> None:
    item = candidate(setup="unclear")
    item["reasons"] = ["forming support retest near local range low"]
    intent = evaluate_order_intent_candidate(item, reservation=empty_reservation())
    assert intent["setup_family"] == "support_retest"
    assert intent["status"] == "intent_preview_ready"


def test_bad_volume_soft_in_non_breakout_context_and_hard_for_unconfirmed_breakout() -> None:
    soft = evaluate_order_intent_candidate(candidate(setup="mean_reversion", volume_vs_avg="0.50"), reservation=empty_reservation())
    assert "bad_volume_or_momentum" in soft["soft_blockers"]
    assert "bad_volume_or_momentum" not in soft["hard_blockers"]
    assert soft["status"] == "near_miss_intent"

    hard = evaluate_order_intent_candidate(candidate(setup="breakout", volume_vs_avg="0.50", momentum="down"), reservation=empty_reservation())
    assert "bad_volume_or_momentum" in hard["hard_blockers"]
    assert hard["status"] == "candidate_rejected"


def test_near_miss_output_works_in_report() -> None:
    report = build_multi_order_intent_preview_report(
        candidates=[candidate(setup="unclear")],
        open_orders_state={"orders": {}},
        positions_state={},
        selected_tests_summary={"selected_tests_classification": "OK"},
    )
    assert report["preview_ready_intent_count"] == 0
    assert report["near_miss_intent_count"] == 1
    assert report["top_near_miss_intents"][0]["ticker"] == "BTC-USDC"
    assert report["hard_rejected_candidate_count"] == 0
    assert report["btc_usdc_explanation"]["status"] == "near_miss_intent"


def test_market_orders_disabled_by_default_and_future_ack_gated() -> None:
    intent = evaluate_order_intent_candidate(candidate(order_type="market"), reservation=empty_reservation())
    assert intent["market_order_preview"] is True
    assert "market_orders_disabled_by_default" in intent["blockers"]
    assert "market_orders_future_ack_required" in intent["blockers"]
    assert intent["live_submit_eligibility"] is False


def test_sell_intents_preview_only_no_oversell_and_duplicate_exit_rejection() -> None:
    positions = {"BTC-USDC": {"ticker": "BTC-USDC", "status": "open", "bot_managed_base": "0.1", "position_size_base": "0.1"}}
    reservation = build_reservation_preview(open_orders_state={"orders": {}}, positions_state=positions, quote_available="250")
    sell = evaluate_order_intent_candidate(
        candidate(side="SELL", setup="trend_continuation", support="98", resistance="108", size_base="0.05"),
        reservation=reservation,
    )
    assert sell["sell_order_preview"] is True
    assert sell["live_submit_eligibility"] is False
    assert "sell_intents_preview_only_live_sell_disabled" in sell["warnings"]

    oversell = evaluate_order_intent_candidate(candidate(side="SELL", size_base="0.2"), reservation=reservation)
    assert "sell_no_oversell_blocked" in oversell["blockers"]

    duplicate_reservation = build_reservation_preview(
        open_orders_state={"orders": {"s": {"ticker": "BTC-USDC", "side": "SELL", "status": "submitted", "remaining_size": "0.02"}}},
        positions_state=positions,
        quote_available="250",
    )
    duplicate = evaluate_order_intent_candidate(candidate(side="SELL", size_base="0.01"), reservation=duplicate_reservation)
    assert "duplicate_sell_exit_rejected" in duplicate["blockers"]


def test_selected_tests_audit_blocker_and_strict_route_untouched() -> None:
    report = build_multi_order_intent_preview_report(
        candidates=[candidate()],
        open_orders_state={"orders": {}},
        positions_state={},
        selected_tests_summary={"selected_tests_classification": "WATCH"},
    )
    assert "selected_tests_audit_blocker" in report["blockers"]
    assert report["strict_approve_trade_route_touched"] is False
    root = Path(__file__).resolve().parents[1]
    source = (root / "bot/phase_c43_autonomous_entry_live.py").read_text(encoding="utf-8")
    assert "judge_approve_trade" in source
    assert "submit_live=True" in source or "submit_live" in source


def test_cli_writes_reports_d6_only_and_does_not_mutate_state(tmp_path: Path) -> None:
    root = tmp_path
    (root / "state").mkdir()
    (root / "logs").mkdir()
    (root / "reports/d6").mkdir(parents=True)
    open_before = {"orders": {}}
    pos_before = {}
    (root / "state/open_orders.json").write_text(json.dumps(open_before), encoding="utf-8")
    (root / "state/positions.json").write_text(json.dumps(pos_before), encoding="utf-8")
    (root / "logs/analysis.jsonl").write_text(json.dumps(candidate()) + "\n", encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools/build_d6_multi_order_intent_preview.py"),
            "--root",
            str(root),
            "--json-out",
            str(root / "reports/d6/intent-preview.json"),
            "--markdown-out",
            str(root / "reports/d6/intent-preview.md"),
        ],
        cwd=project_root,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "d6_multi_order_intent_preview" in result.stdout
    payload = json.loads((root / "reports/d6/intent-preview.json").read_text(encoding="utf-8"))
    assert payload["preview_only"] is True
    assert payload["state_write_performed"] is False
    assert json.loads((root / "state/open_orders.json").read_text(encoding="utf-8")) == open_before
    assert json.loads((root / "state/positions.json").read_text(encoding="utf-8")) == pos_before
