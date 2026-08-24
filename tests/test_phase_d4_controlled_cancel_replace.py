from __future__ import annotations

import json
from pathlib import Path

from bot.live_exit_gate import D4_CONTROLLED_CANCEL_REPLACE_ACK
from bot.phase_d4_controlled_cancel_replace import run_phase_d4_controlled_cancel_replace


TICKER = "BTC-USDC"
CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _order(**overrides):
    payload = {
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "order_id": EXCHANGE_ORDER_ID,
        "ticker": TICKER,
        "product_id": TICKER,
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "d3_exit_label": "TP1",
        "linked_position_id": LINKED_POSITION_ID,
        "execution_action": "place_limit_sell",
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
        "ticker": TICKER,
        "status": "open",
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
        "available_base_after_reservations": "0.0000649067431275",
    }
    payload.update(overrides)
    return payload


def _write_state(tmp_path: Path, *, orders=None, position=None):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    orders_file = state_dir / "open_orders.json"
    positions_file = state_dir / "positions.json"
    events_file = logs_dir / "order_events.jsonl"
    selected_orders = orders if orders is not None else [_order()]
    orders_file.write_text(
        json.dumps({"orders": {item["client_order_id"]: item for item in selected_orders}}, indent=2),
        encoding="utf-8",
    )
    positions_file.write_text(json.dumps({TICKER: position or _position()}, indent=2), encoding="utf-8")
    events_file.write_text("", encoding="utf-8")
    return orders_file, positions_file, events_file


def _open_snapshot(**overrides):
    payload = {
        "raw_status": "OPEN",
        "normalized_status": "open",
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
    }
    payload.update(overrides)
    return payload


def _market(**overrides):
    payload = {"best_bid": "73500.00", "best_ask": "73500.01", "mid_price": "73500.005"}
    payload.update(overrides)
    return payload


def _rules(**overrides):
    payload = {"base_increment": "0.00000001", "price_increment": "0.01", "min_order_quote": "1"}
    payload.update(overrides)
    return payload


class FakeCoinbaseClient:
    def __init__(self, *, cancel_response=None, submit_response=None, cancel_exc=None, submit_exc=None):
        self.cancel_response = cancel_response if cancel_response is not None else {"success": True, "order_ids": [EXCHANGE_ORDER_ID]}
        self.submit_response = submit_response if submit_response is not None else {"success": True, "order_id": "replacement-order-1"}
        self.cancel_exc = cancel_exc
        self.submit_exc = submit_exc
        self.cancel_calls = []
        self.submit_calls = []

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        if self.cancel_exc:
            raise self.cancel_exc
        return self.cancel_response

    def place_limit_order(self, **kwargs):
        self.submit_calls.append(dict(kwargs))
        if self.submit_exc:
            raise self.submit_exc
        return self.submit_response


def _run(tmp_path, *, client=None, **overrides):
    orders_file, positions_file, events_file = _write_state(
        tmp_path,
        orders=overrides.pop("orders", None),
        position=overrides.pop("position", None),
    )
    kwargs = dict(
        ticker=TICKER,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        replacement_price="76000.00",
        ack=D4_CONTROLLED_CANCEL_REPLACE_ACK,
        one_shot_armed_process_local=True,
        coinbase_client=client,
        orders_file=orders_file,
        positions_file=positions_file,
        order_events_file=events_file,
        lifecycle_snapshot=_open_snapshot(),
        market_snapshot=_market(),
        product_rules=_rules(),
    )
    kwargs.update(overrides)
    return run_phase_d4_controlled_cancel_replace(**kwargs), orders_file, positions_file


def test_preview_ready_proves_before_and_after_cancel_gate(tmp_path):
    report, orders_file, positions_file = _run(tmp_path)

    assert report["status"] == "d4_controlled_cancel_replace_preflight_ready"
    assert report["cancel_attempted"] is False
    assert report["replacement_submit_attempted"] is False
    assert "d4_replacement_confirmed_cancel_required" in report["replacement_submit_gate_before_cancel"]["blockers"]
    assert report["replacement_submit_gate_after_simulated_cancel"]["allowed"] is True
    assert len(json.loads(orders_file.read_text(encoding="utf-8"))["orders"]) == 1
    assert "replacement-order-1" not in orders_file.read_text(encoding="utf-8")
    assert json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]["reserved_base_open_exit_orders"] == "0.00006489"


def test_wrong_ack_blocks_before_cancel(tmp_path):
    report, _, _ = _run(tmp_path, ack="WRONG")
    assert report["status"] == "d4_controlled_cancel_replace_preflight_blocked"
    assert "d4_ack_missing_or_invalid" in report["blockers"]
    assert report["cancel_attempted"] is False


def test_fill_evidence_routes_to_d3_lifecycle_before_cancel(tmp_path):
    report, _, _ = _run(
        tmp_path,
        lifecycle_snapshot=_open_snapshot(normalized_status="partially_filled", filled_base="0.00001", fill_count=1),
    )
    assert "fill_evidence_route_to_d3_lifecycle_apply" in report["blockers"]
    assert report["cancel_attempted"] is False


def test_duplicate_open_exit_blocks_before_cancel(tmp_path):
    duplicate = _order(client_order_id="duplicate", exchange_order_id="duplicate-exchange", order_id="duplicate-exchange")
    report, _, _ = _run(tmp_path, orders=[_order(), duplicate])
    assert "open_d3_exit_count_not_one" in report["blockers"]
    assert report["cancel_attempted"] is False


class TransientThenCancelledCoinbaseClient(FakeCoinbaseClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.get_order_call_count = 0

    def get_order(self, order_id):
        self.get_order_call_count += 1
        if self.get_order_call_count < 3:
            return {
                "order": {
                    "order_id": order_id,
                    "status": "OPEN",
                    "filled_size": "0",
                    "filled_value": "0",
                    "average_filled_price": "0",
                    "number_of_fills": "0",
                    "product_id": TICKER,
                    "side": "SELL",
                }
            }
        return {
            "order": {
                "order_id": order_id,
                "status": "CANCELLED",
                "filled_size": "0",
                "filled_value": "0",
                "average_filled_price": "0",
                "number_of_fills": "0",
                "product_id": TICKER,
                "side": "SELL",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


def test_retries_post_cancel_confirmation_past_transient_open_status(tmp_path):
    # Regression test for the same race-condition class fixed live 2026-07-08 in
    # the sibling controlled stop-exit path: a post-cancel confirmation lookup
    # taken immediately after cancel_order can read back a transient
    # non-terminal status before Coinbase's backend settles. A brief retry must
    # pick up the real terminal status instead of blocking a valid replacement.
    # No post_cancel_snapshot is passed here (unlike every other live-route
    # test in this file) specifically so _resolve_lifecycle_snapshot actually
    # calls get_order instead of bypassing it.
    client = TransientThenCancelledCoinbaseClient()
    report, _, _ = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
        post_cancel_confirmation_retry_seconds=0,
    )

    assert client.get_order_call_count == 3
    assert report["status"] == "d4_controlled_cancel_replace_applied"
    assert report["cancel_confirmed"] is True


def test_happy_live_route_cancel_first_then_submit_and_updates_state(tmp_path):
    client = FakeCoinbaseClient()
    report, orders_file, positions_file = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
        post_cancel_snapshot=_open_snapshot(raw_status="CANCELLED", normalized_status="cancelled"),
    )

    assert report["status"] == "d4_controlled_cancel_replace_applied"
    assert client.cancel_calls == [EXCHANGE_ORDER_ID]
    assert len(client.submit_calls) == 1
    assert client.submit_calls[0]["side"] == "SELL"
    assert str(client.submit_calls[0]["limit_price"]) == "76000.00"
    assert str(client.submit_calls[0]["base_size"]) == "0.00006489"
    state = json.loads(orders_file.read_text(encoding="utf-8"))["orders"]
    old = state[CLIENT_ORDER_ID]
    assert old["status"] == "cancelled"
    new_orders = [order for cid, order in state.items() if cid != CLIENT_ORDER_ID]
    assert len(new_orders) == 1
    assert new_orders[0]["limit_price"] == "76000.00"
    assert new_orders[0]["status"] == "submitted"
    position = json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]
    assert position["reserved_base_open_exit_orders"] == "0.00006489"
    assert report["open_d3_exit_count_after"] == 1
    assert report["duplicate_open_exit_detected_after"] is False


def test_coinbase_results_success_cancel_shape_is_confirmed(tmp_path):
    client = FakeCoinbaseClient(cancel_response={"results": [{"order_id": EXCHANGE_ORDER_ID, "success": True}]})
    report, _, _ = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
        post_cancel_snapshot=_open_snapshot(raw_status="CANCELLED", normalized_status="cancelled"),
    )

    assert report["status"] == "d4_controlled_cancel_replace_applied"
    assert client.cancel_calls == [EXCHANGE_ORDER_ID]
    assert len(client.submit_calls) == 1


def test_resume_after_confirmed_cancel_does_not_call_cancel_again(tmp_path):
    client = FakeCoinbaseClient()
    orders_file, positions_file, events_file = _write_state(
        tmp_path,
        orders=[_order(status="cancelled")],
    )
    report = run_phase_d4_controlled_cancel_replace(
        ticker=TICKER,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        replacement_price="76000.00",
        ack=D4_CONTROLLED_CANCEL_REPLACE_ACK,
        one_shot_armed_process_local=True,
        coinbase_client=client,
        orders_file=orders_file,
        positions_file=positions_file,
        order_events_file=events_file,
        lifecycle_snapshot=_open_snapshot(raw_status="CANCELLED", normalized_status="cancelled"),
        market_snapshot=_market(),
        product_rules=_rules(),
        allow_live_cancel=False,
        allow_live_replace=True,
        resume_after_confirmed_cancel=True,
    )

    assert report["status"] == "d4_controlled_cancel_replace_applied"
    assert client.cancel_calls == []
    assert len(client.submit_calls) == 1
    state = json.loads(orders_file.read_text(encoding="utf-8"))["orders"]
    assert state[CLIENT_ORDER_ID]["status"] == "cancelled"


def test_cancel_only_confirms_and_stops_before_replacement(tmp_path):
    client = FakeCoinbaseClient()
    report, orders_file, positions_file = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=False,
        cancel_only_after_confirmed_cancel=True,
        post_cancel_snapshot=_open_snapshot(raw_status="CANCELLED", normalized_status="cancelled"),
    )

    assert report["status"] == "d4_controlled_cancel_replace_cancel_confirmed_replacement_pending"
    assert client.cancel_calls == [EXCHANGE_ORDER_ID]
    assert client.submit_calls == []
    assert report["replacement_submit_attempted"] is False
    state = json.loads(orders_file.read_text(encoding="utf-8"))["orders"]
    assert state[CLIENT_ORDER_ID]["status"] == "cancelled"
    position = json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]
    assert position["reserved_base_open_exit_orders"] == "0.00006489"


def test_cancel_uncertain_does_not_submit_or_write_state(tmp_path):
    client = FakeCoinbaseClient(cancel_response={"success": True, "order_ids": []})
    report, orders_file, positions_file = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
    )

    assert report["status"] == "d4_controlled_cancel_replace_cancel_uncertain_no_replace"
    assert client.cancel_calls == [EXCHANGE_ORDER_ID]
    assert client.submit_calls == []
    assert report["state_write_performed"] is False
    assert json.loads(orders_file.read_text(encoding="utf-8"))["orders"][CLIENT_ORDER_ID]["status"] == "submitted"
    assert json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]["reserved_base_open_exit_orders"] == "0.00006489"


def test_post_cancel_not_cancelled_does_not_submit_or_write_state(tmp_path):
    client = FakeCoinbaseClient()
    report, orders_file, _ = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
        post_cancel_snapshot=_open_snapshot(normalized_status="open"),
    )

    assert report["status"] == "d4_controlled_cancel_replace_cancel_uncertain_no_replace"
    assert "post_cancel_status_not_cancelled:open" in report["blockers"]
    assert client.submit_calls == []
    assert json.loads(orders_file.read_text(encoding="utf-8"))["orders"][CLIENT_ORDER_ID]["status"] == "submitted"


def test_submit_failure_after_confirmed_cancel_records_cancel_and_unreserves(tmp_path):
    client = FakeCoinbaseClient(submit_exc=RuntimeError("submit boom"))
    report, orders_file, positions_file = _run(
        tmp_path,
        client=client,
        allow_live_cancel=True,
        allow_live_replace=True,
        post_cancel_snapshot=_open_snapshot(raw_status="CANCELLED", normalized_status="cancelled"),
    )

    assert report["status"] == "d4_controlled_cancel_replace_replacement_submit_failed"
    assert client.cancel_calls == [EXCHANGE_ORDER_ID]
    assert len(client.submit_calls) == 1
    assert json.loads(orders_file.read_text(encoding="utf-8"))["orders"][CLIENT_ORDER_ID]["status"] == "cancelled"
    assert json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]["reserved_base_open_exit_orders"] == "0"
