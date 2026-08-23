from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.phase_d4_trailing_preview import (
    build_phase_d4_trailing_market_path_preview,
    build_phase_d4_trailing_preview_report,
)


NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _order(**overrides):
    payload = {
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "order_id": EXCHANGE_ORDER_ID,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": LINKED_POSITION_ID,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
        "limit_price": "84800.00",
        "post_only": True,
        "reduce_only_local": True,
    }
    payload.update(overrides)
    return payload


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "recovery_linked_position_id": LINKED_POSITION_ID,
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
    }
    payload.update(overrides)
    return payload


def _market(*, bid="84499.99", ask="84500.00", mid="84500.00", timestamp=None):
    return {
        "best_bid": bid,
        "best_ask": ask,
        "mid_price": mid,
        "timestamp": (timestamp or NOW).isoformat(),
    }


def _market_path(*mids: str):
    path = []
    for offset, mid in enumerate(mids):
        value = float(mid)
        path.append(
            _market(
                bid=f"{value - 0.01:.2f}",
                ask=f"{value:.2f}",
                mid=f"{value:.2f}",
                timestamp=NOW + timedelta(seconds=offset),
            )
        )
    return path


def _rules(**overrides):
    payload = {
        "base_increment": "0.00000001",
        "price_increment": "0.01",
        "min_order_quote": "1",
    }
    payload.update(overrides)
    return payload


def _policy(**overrides):
    payload = {
        "activation_price": "85000.00",
        "trailing_distance_pct": "0.02",
        "refresh_tolerance_pct": "0.001",
        "cooldown_seconds": 300,
        "stale_book_seconds": 60,
    }
    payload.update(overrides)
    return payload


def _report(*, order=None, position=None, market=None, rules=None, policy=None, open_orders=None):
    current_order = order if order is not None else _order()
    orders = open_orders if open_orders is not None else [current_order]
    return build_phase_d4_trailing_preview_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED_POSITION_ID,
        current_order=current_order,
        position=position or _position(),
        market_snapshot=market or _market(),
        product_rules=rules or _rules(),
        policy=policy or _policy(),
        open_orders=orders,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        now=NOW,
    )


def _path_report(path, *, order=None, position=None, rules=None, policy=None, open_orders=None):
    current_order = order if order is not None else _order()
    orders = open_orders if open_orders is not None else [current_order]
    return build_phase_d4_trailing_market_path_preview(
        ticker="BTC-USDC",
        linked_position_id=LINKED_POSITION_ID,
        market_path=path,
        current_order=current_order,
        position=position or _position(),
        product_rules=rules or _rules(),
        policy=policy or _policy(),
        open_orders=orders,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        now=NOW,
    )


def _assert_preview_safety(report):
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["cancel_replace_allowed"] is False


def test_price_far_below_activation_keeps_open_without_candidate():
    report = _report(market=_market(bid="79999.99", ask="80000.00", mid="80000.00"))

    assert report["status"] == "d4_trailing_preview_keep_open"
    assert report["activation_state"] == "inactive"
    assert report["proposed_action"] == "keep_open"
    assert report["reason"] == "price_below_activation"
    assert report["proposed_replacement_price"] == ""
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["cancel_replace_allowed"] is False


def test_below_activation_market_path_keeps_open_inactive_without_candidate():
    report = _path_report(_market_path("80000.00", "82000.00", "84999.99"))

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_keep_open"
    assert report["final_proposed_action"] == "keep_open"
    assert report["reports"][-1]["activation_state"] == "inactive"
    assert all(step["proposed_replacement_price"] == "" for step in report["reports"])


def test_price_above_activation_records_active_peak_reference():
    report = _report(market=_market(bid="85999.99", ask="86000.00", mid="86000.00"))

    assert report["status"] == "d4_trailing_preview_keep_open"
    assert report["activation_state"] == "active"
    assert report["peak_reference_price"] == "86000.00"
    assert report["trailing_stop_price"] == "84280.0000"
    assert report["proposed_action"] == "keep_open"


def test_activation_then_continued_rise_updates_peak_and_keeps_open():
    report = _path_report(_market_path("84900.00", "85100.00", "86000.00", "87250.00"))

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_keep_open"
    assert report["final_proposed_action"] == "keep_open"
    assert report["final_peak_reference_price"] == "87250.00"
    assert report["reports"][-1]["activation_state"] == "active"
    assert report["reports"][-1]["reason"] == "trailing_stop_not_triggered"


def test_activation_then_small_pullback_inside_trailing_distance_keeps_open():
    report = _path_report(_market_path("85100.00", "86000.00", "84500.00"))

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_keep_open"
    assert report["final_proposed_action"] == "keep_open"
    assert report["reports"][-1]["activation_state"] == "active"
    assert report["reports"][-1]["trailing_stop_price"] == "84280.0000"
    assert report["reports"][-1]["reason"] == "trailing_stop_not_triggered"


def test_small_drift_inside_refresh_tolerance_keeps_open():
    report = _report(
        order=_order(limit_price="84800.00"),
        market=_market(bid="84799.98", ask="84799.99", mid="84750.00"),
        policy=_policy(prior_peak_price="86500.00", refresh_tolerance_pct="0.01"),
    )

    assert report["status"] == "d4_trailing_preview_keep_open"
    assert report["activation_state"] == "active"
    assert report["reason"] == "candidate_inside_refresh_tolerance"
    assert report["proposed_action"] == "keep_open"
    assert report["requires_future_ack"] is False


def test_activation_then_trailing_trigger_path_returns_preview_candidate():
    report = _path_report(_market_path("85100.00", "86000.00", "83000.00"))

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_candidate_ready"
    assert report["final_proposed_action"] == "preview_reprice_candidate"
    assert report["reports"][-1]["requires_future_ack"] is True
    assert report["reports"][-1]["proposed_replacement_price"] == "84280.00"


def test_price_falls_enough_returns_preview_reprice_candidate():
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00"),
        policy=_policy(prior_peak_price="86000.00"),
    )

    assert report["status"] == "d4_trailing_preview_candidate_ready"
    assert report["activation_state"] == "active"
    assert report["proposed_action"] == "preview_reprice_candidate"
    assert report["reason"] == "trailing_stop_triggered_candidate_preview_only"
    assert report["proposed_replacement_price"] == "84280.00"
    assert report["requires_future_ack"] is True
    assert report["cancel_replace_allowed"] is False
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False


def test_trailing_candidate_remains_preview_only_no_live_replace():
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00"),
        policy=_policy(prior_peak_price="86000.00"),
    )
    assert report["status"] == "d4_trailing_preview_candidate_ready"
    assert report["requires_future_ack"] is True
    assert report["cancel_replace_allowed"] is False
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True


def test_gap_down_through_trailing_stop_returns_preview_only_candidate():
    report = _path_report(_market_path("85000.00", "88000.00", "81000.00"))

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_candidate_ready"
    assert report["final_proposed_action"] == "preview_reprice_candidate"
    assert report["final_reason"] == "trailing_stop_triggered_candidate_preview_only"
    assert report["reports"][-1]["proposed_replacement_price"] == "86240.00"
    assert report["reports"][-1]["requires_future_ack"] is True


def test_candidate_below_min_order_quote_blocks():
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00"),
        rules=_rules(min_order_quote="10"),
        policy=_policy(prior_peak_price="86000.00"),
    )

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "candidate_below_min_order_quote" in report["blockers"]
    assert report["requires_future_ack"] is False


def test_product_rule_rounding_respects_price_increment():
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00"),
        rules=_rules(price_increment="0.05", min_order_quote="1"),
        policy=_policy(prior_peak_price="86000.03"),
    )

    assert report["status"] == "d4_trailing_preview_candidate_ready"
    assert report["proposed_action"] == "preview_reprice_candidate"
    assert report["proposed_replacement_price"] == "84280.05"
    assert report["requires_future_ack"] is True
    _assert_preview_safety(report)


def test_candidate_crosses_book_post_only_unsafe_blocks():
    report = _report(
        market=_market(bid="84280.01", ask="84280.02", mid="83000.00"),
        policy=_policy(prior_peak_price="86000.00", candidate_price_override="84280.00"),
    )

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "candidate_crosses_book_post_only_unsafe" in report["blockers"]
    assert report["post_only_feasible"] is False


def test_trigger_with_stale_book_blocks_without_candidate():
    stale_time = NOW - timedelta(seconds=120)
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00", timestamp=stale_time),
        policy=_policy(prior_peak_price="86000.00"),
    )

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "market_snapshot_stale" in report["blockers"]
    assert report["proposed_replacement_price"] == ""
    _assert_preview_safety(report)


def test_stale_market_snapshot_blocks():
    stale_time = NOW - timedelta(seconds=61)
    report = _report(market=_market(timestamp=stale_time))

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "market_snapshot_stale" in report["blockers"]
    assert report["market_snapshot_stale"] is True


def test_cooldown_blocks_repeated_candidate_after_recent_candidate_time():
    report = _report(
        market=_market(bid="82999.99", ask="83000.00", mid="83000.00"),
        policy=_policy(
            prior_peak_price="86000.00",
            last_candidate_at=(NOW - timedelta(seconds=120)).isoformat(),
            cooldown_seconds=300,
        ),
    )

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "cooldown_active" in report["blockers"]
    assert report["cooldown_active"] is True
    assert report["proposed_replacement_price"] == ""


def test_cooldown_active_blocks():
    report = _report(policy=_policy(cooldown_until=(NOW + timedelta(seconds=30)).isoformat()))

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert "cooldown_active" in report["blockers"]
    assert report["cooldown_active"] is True


def test_candidate_inside_refresh_tolerance_path_avoids_churn():
    report = _path_report(
        _market_path("85100.00", "86500.00", "84750.00"),
        order=_order(limit_price="84800.00"),
        policy=_policy(refresh_tolerance_pct="0.01"),
    )

    _assert_preview_safety(report)
    assert report["final_status"] == "d4_trailing_preview_keep_open"
    assert report["final_proposed_action"] == "keep_open"
    assert report["final_reason"] == "candidate_inside_refresh_tolerance"
    assert report["reports"][-1]["requires_future_ack"] is False


def test_duplicate_open_d3_exits_blocks_p0():
    first = _order()
    second = _order(
        client_order_id="phased3-BTCUSDC-TP1-duplicate",
        exchange_order_id="duplicate-exchange-order",
        order_id="duplicate-exchange-order",
    )
    report = _report(order=first, open_orders=[first, second])

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert report["duplicate_open_d3_exit_detected"] is True
    assert "duplicate_open_d3_exit_orders_for_position" in report["blockers"]


def test_reserved_base_mismatch_blocks_oversell_safety():
    report = _report(position=_position(reserved_base_open_exit_orders="0.00001"))

    assert report["status"] == "d4_trailing_preview_blocked"
    assert report["proposed_action"] == "blocked"
    assert report["oversell_detected"] is True
    assert "reserved_base_less_than_open_exit_size" in report["blockers"]
    _assert_preview_safety(report)


def test_preview_tool_uses_fixtures_and_never_calls_coinbase_or_writes_real_state(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    orders_file = state_dir / "open_orders.json"
    positions_file = state_dir / "positions.json"
    market_file = tmp_path / "market.json"
    rules_file = tmp_path / "rules.json"
    policy_file = tmp_path / "policy.json"
    orders_file.write_text(json.dumps({"orders": {CLIENT_ORDER_ID: _order()}}, indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps({"positions": {"BTC-USDC": _position()}}, indent=2), encoding="utf-8")
    market_file.write_text(json.dumps(_market(bid="82999.99", ask="83000.00", mid="83000.00"), indent=2), encoding="utf-8")
    rules_file.write_text(json.dumps(_rules(), indent=2), encoding="utf-8")
    policy_file.write_text(json.dumps(_policy(prior_peak_price="86000.00"), indent=2), encoding="utf-8")

    before_orders = orders_file.read_text(encoding="utf-8")
    before_positions = positions_file.read_text(encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d4_trailing_preview.py",
            "--ticker",
            "BTC-USDC",
            "--client-order-id",
            CLIENT_ORDER_ID,
            "--exchange-order-id",
            EXCHANGE_ORDER_ID,
            "--linked-position-id",
            LINKED_POSITION_ID,
            "--orders-file",
            str(orders_file),
            "--positions-file",
            str(positions_file),
            "--market-fixture",
            str(market_file),
            "--product-rules-fixture",
            str(rules_file),
            "--policy-fixture",
            str(policy_file),
            "--now",
            NOW.isoformat(),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["status"] == "d4_trailing_preview_candidate_ready"
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert orders_file.read_text(encoding="utf-8") == before_orders
    assert positions_file.read_text(encoding="utf-8") == before_positions
