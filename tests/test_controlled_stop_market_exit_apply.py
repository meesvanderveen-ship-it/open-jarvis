from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
from bot.controlled_stop_market_exit_plan import apply_controlled_stop_market_exit
from bot.order_store import OrderStore
from bot.state_store import StateStore


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _seed_position(state: StateStore, **overrides) -> None:
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "position_size_base": "0.00015416",
        "bot_managed_base": "0.00015416",
        "reserved_base_open_exit_orders": "0.00015416",
        "entry_price": "74100",
        "stop_price": "74100",
        "last_heartbeat_reason": "stop_breached_or_below_invalidation",
        "monitoring_enabled": True,
    }
    payload.update(overrides)
    state.upsert_position("BTC-USDC", payload)


def _seed_tp(orders: OrderStore, **overrides) -> None:
    payload = {
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00015416",
        "remaining_size": "0.00015416",
        "limit_price": "71554.19",
    }
    payload.update(overrides)
    orders.upsert_order(payload)


def _cfg(**overrides):
    base = {
        "enable_controlled_stop_market_exits": False,
        "enable_autonomous_stop_exit_cancel": False,
        "enable_autonomous_stop_exit_submit": False,
        "enable_autonomous_stop_exit_apply": False,
        "mode_b_controlled_stop_exit_ack": "",
        "controlled_stop_exit_max_quote_usd": "25.00",
        "controlled_stop_exit_require_open_tp_cancel_first": True,
        "controlled_stop_exit_order_type": "near_market_limit_ioc",
        "controlled_stop_exit_max_slippage_pct": "0.0100",
        "market_order_enabled": False,
        "enable_market_orders": False,
        "allow_market_orders": False,
        "mode_c_market_order_ack": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _armed_cfg(**overrides):
    return _cfg(
        enable_controlled_stop_market_exits=True,
        enable_autonomous_stop_exit_cancel=True,
        enable_autonomous_stop_exit_submit=True,
        enable_autonomous_stop_exit_apply=True,
        mode_b_controlled_stop_exit_ack=MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
        **overrides,
    )


class FakeCoinbaseClient:
    def __init__(
        self,
        *,
        cancel_ok: bool = True,
        fill_status: str = "FILLED",
        filled_size: str = "0.00015416",
        ioc_submit_accepted: bool = True,
    ):
        self.cancel_ok = cancel_ok
        self.fill_status = fill_status
        self.filled_size = filled_size
        self.ioc_submit_accepted = ioc_submit_accepted
        self.cancel_calls: list = []
        self.ioc_calls: list = []
        self.get_order_calls: list = []

    def cancel_order(self, order_id: str):
        self.cancel_calls.append(order_id)
        if self.cancel_ok:
            # Real Coinbase batch_cancel shape only -- no success_results/
            # order_ids/cancelled_order_ids fallback fields, since the real
            # API never actually returns those (see regression test below).
            return {"results": [{"success": True, "order_id": order_id, "failure_reason": ""}]}
        return {"results": [{"success": False, "order_id": order_id, "failure_reason": "UNKNOWN_CANCEL_FAILURE_REASON"}]}

    def place_limit_order_ioc(self, **kwargs):
        self.ioc_calls.append(kwargs)
        # Real Coinbase /orders shape only: the order id is nested under
        # success_response, never a top-level order_id/id (see regression test
        # below). A rejected order is real-shaped too: HTTP 200, success=false,
        # no success_response at all.
        if not self.ioc_submit_accepted:
            return {
                "success": False,
                "error_response": {"error": "INSUFFICIENT_FUND", "message": "Insufficient balance in source account"},
                "order_configuration": kwargs,
            }
        return {
            "success": True,
            "success_response": {"order_id": "ioc-order-1", "client_order_id": kwargs.get("client_order_id")},
            "order_configuration": kwargs,
        }

    def get_order(self, order_id: str):
        self.get_order_calls.append(order_id)
        return {"order": {"status": self.fill_status, "filled_size": self.filled_size, "average_filled_price": "71000"}}

    def get_product(self, product_id: str):
        return {"product_id": product_id, "price_increment": "0.01", "base_increment": "0.00000001"}


def _market_context():
    return {"current_price": "71000", "mid_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]}


def test_apply_is_preview_only_when_mode_b_not_armed(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_cfg(),  # Mode B flags all off (default/current behavior)
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "mode_b_not_armed_preview_only"
    assert client.cancel_calls == []
    assert client.ioc_calls == []


def test_apply_cancels_existing_tp_then_submits_ioc_and_confirms_fill(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "filled_awaiting_local_apply"
    assert client.cancel_calls == ["81edc268-cf15-4f25-b30b-f0d5b3abb30d"]
    assert len(client.ioc_calls) == 1
    assert client.ioc_calls[0]["side"] == "SELL"
    assert result["filled_base"] == "0.00015416"
    # the stale TP must be marked cancelled locally, not left open
    tp_order = orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000")
    assert tp_order["status"] == "cancelled"


def test_apply_recognizes_real_coinbase_batch_cancel_response_shape(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident (2026-07-06): a stop breach on
    # SOL-USDC correctly triggered Mode B, which really did cancel the stale
    # TP order on Coinbase (confirmed live via a read-only get_order lookup:
    # status "CANCELLED"). But _normalize_cancel_result only recognized a
    # flat success_results/order_ids/cancelled_order_ids list, a shape the
    # real batch_cancel endpoint never returns -- its actual response is
    # {"results": [{"success": bool, "order_id": ..., "failure_reason": ...}]}.
    # The mismatch reported "cancel_not_confirmed" for a cancel that had
    # already succeeded, aborting Mode B before the protective stop-sell was
    # ever submitted and leaving the position unprotected after a real stop
    # breach. This client returns *only* the real shape (no legacy fallback
    # fields), so a regression here must fail loudly instead of being masked
    # by a too-generous test double.
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "filled_awaiting_local_apply"
    assert result["cancel_result"] == {
        "cancel_succeeded": True,
        "cancel_normalized_status": "cancelled",
        "cancel_error_message": "",
    }
    assert len(client.ioc_calls) == 1


def test_apply_handles_real_ioc_submit_success_shape_without_crashing(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident (2026-07-08): immediately after fixing
    # the sor_limit_ioc field name, the very next controlled-stop-exit attempt on
    # SOL-USDC crashed with an uncaught ValueError ("live open order records
    # require exchange_order_id") instead of completing. The real Coinbase accept
    # shape nests the order id under success_response, never top-level order_id/id
    # -- the naive extraction here matched neither, wrote an "open"/"live" order
    # record with an empty exchange_order_id, and OrderStore's own safety guard
    # against exactly that raised before this function ever returned, aborting
    # the whole ticker's cycle and losing the result/diagnosis entirely.
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "filled_awaiting_local_apply"
    assert len(client.ioc_calls) == 1
    assert result["submit_result"]["success_response"]["order_id"] == "ioc-order-1"


def test_apply_handles_ioc_submit_rejection_without_crashing(tmp_path: Path, monkeypatch) -> None:
    # Companion to the success-shape regression above: a genuine Coinbase
    # rejection (HTTP 200, success=false, no success_response/order_id at all) is
    # not an exception -- place_limit_order_ioc returns normally. Before this fix,
    # the empty extracted exchange_order_id still reached the same
    # store.upsert_order("status": "submitted", "mode": "live", ...) call, which
    # crashed with an uncaught ValueError instead of surfacing the rejection.
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient(ioc_submit_accepted=False)

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "ioc_submit_missing_exchange_order_id"
    assert result["submit_result"]["success"] is False
    assert result["submit_result"]["error_response"]["error"] == "INSUFFICIENT_FUND"


def test_apply_rounds_ioc_limit_price_to_product_price_increment(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident (2026-07-08): the raw slippage-adjusted
    # limit_price (current_price * (1 - max_slippage_pct)) is a Decimal that keeps
    # every input decimal place, e.g. 71000.33 * 0.99 = 70290.3267. Coinbase
    # rejects any price with more decimals than the product's own price_increment
    # (SOL-USDC's real incident: 76.3834500 rejected with INVALID_PRICE_PRECISION,
    # tick size 0.01) -- this path never rounded to it before submitting, unlike
    # every other order-submission path in this codebase.
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context={"current_price": "71000.33", "mid_price": "71000.33", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "filled_awaiting_local_apply"
    assert len(client.ioc_calls) == 1
    assert client.ioc_calls[0]["limit_price"] == Decimal("70290.32")


def test_apply_stops_if_cancel_not_confirmed(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient(cancel_ok=False)

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "cancel_not_confirmed"
    assert client.ioc_calls == []


def test_apply_reports_ioc_killed_no_fill(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = FakeCoinbaseClient(fill_status="CANCELLED", filled_size="0")

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert result["status"] == "ioc_killed_no_fill"


def test_apply_retries_fill_lookup_past_transient_open_status(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident (2026-07-08): the SOL-USDC stop-exit
    # order filled completely (18 fills, confirmed on Coinbase and via a direct
    # zero-SOL balance check) but the single immediate get_order lookup here read
    # back status "OPEN" before Coinbase's backend had settled the fill into a
    # queryable state. The code concluded "no fill", marked the order cancelled
    # locally, and never closed the position or recorded the realized loss --
    # silently desyncing local state from a real, already-executed trade until
    # manually reconciled. A brief retry while status is still non-terminal must
    # pick up the fill once it settles.
    class TransientThenFilledCoinbaseClient(FakeCoinbaseClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.get_order_call_count = 0

        def get_order(self, order_id: str):
            self.get_order_call_count += 1
            self.get_order_calls.append(order_id)
            if self.get_order_call_count < 3:
                return {"order": {"status": "OPEN", "filled_size": "0", "average_filled_price": "0"}}
            return {"order": {"status": "FILLED", "filled_size": self.filled_size, "average_filled_price": "71000"}}

    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    client = TransientThenFilledCoinbaseClient()

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=client,
        fill_lookup_retry_seconds=0,
    )

    assert client.get_order_call_count == 3
    assert result["status"] == "filled_awaiting_local_apply"
    assert result["filled_base"] == "0.00015416"


def test_apply_without_coinbase_client_is_blocked(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)

    result = apply_controlled_stop_market_exit(
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        market_context=_market_context(),
        cfg=_armed_cfg(),
        order_store=orders,
        state_store=state,
        coinbase_client=None,
    )

    assert result["status"] == "coinbase_client_missing"
