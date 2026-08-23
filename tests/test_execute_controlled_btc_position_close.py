from __future__ import annotations

import json
from pathlib import Path

from bot.order_store import OrderStore
from bot.state_store import StateStore
from tools import execute_controlled_btc_position_close as close_tool
from tools.execute_controlled_btc_position_close import build_controlled_position_close_report


LINKED = "76310097-849e-481c-b587-ba44bc3330fe"
STALE_CLIENT = "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000"
STALE_EXCHANGE = "81edc268-cf15-4f25-b30b-f0d5b3abb30d"
ACK = "CLOSE_BTC_POSITION_AND_CANCEL_STALE_TP_76310097"


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
        "phase_c43_exchange_order_id": LINKED,
        "recovery_linked_position_id": LINKED,
        "position_size_base": "0.00015416",
        "position_size_quote": "10.950",
        "bot_managed_base": "0.00015416",
        "reserved_base_open_exit_orders": "0.00015416",
        "entry_price": "71000",
        "monitoring_enabled": True,
    }
    payload.update(overrides)
    state.upsert_position("BTC-USDC", payload)


def _seed_tp(orders: OrderStore, **overrides) -> None:
    payload = {
        "client_order_id": STALE_CLIENT,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": LINKED,
        "exchange_order_id": STALE_EXCHANGE,
        "order_id": STALE_EXCHANGE,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00015416",
        "remaining_size": "0.00015416",
        "limit_price": "71554.19",
    }
    payload.update(overrides)
    orders.upsert_order(payload)


def _report(
    tmp_path: Path,
    monkeypatch,
    *,
    ack: str = ACK,
    client=None,
    tp_status: str = "submitted",
    position_overrides=None,
):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, **(position_overrides or {}))
    _seed_tp(orders, status=tp_status, remaining_size="0" if tp_status == "cancelled" else "0.00015416")
    return build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ack,
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )


class _RejectLiveClient:
    def cancel_order(self, *args, **kwargs):
        raise AssertionError("cancel must not be called")

    def _request(self, *args, **kwargs):
        raise AssertionError("submit must not be called")

    def place_market_order(self, *args, **kwargs):
        raise AssertionError("submit must not be called")


class _CancelOnlyClient(_RejectLiveClient):
    def __init__(self):
        self.cancel_calls = []

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return {"success": True, "results": [{"order_id": order_id, "success": True}]}

    def get_order(self, order_id):
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": STALE_CLIENT,
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "CANCELLED",
                "filled_size": "0",
            }
        }

    def get_spot_position(self, ticker):
        raise RuntimeError("stop after cancel verification")


class _ReadyNoSubmitClient(_RejectLiveClient):
    def get_spot_position(self, ticker):
        return {"available_base_balance": "0.00015416"}

    def get_product(self, ticker):
        return {
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_increment": "0.01",
            "quote_min_size": "1",
        }

    def get_product_book(self, ticker, limit=1):
        return {"bids": [{"price": "71000", "size": "1"}], "asks": [{"price": "71001", "size": "1"}]}


class _SubmitAndFilledClient(_ReadyNoSubmitClient):
    def __init__(self):
        self.submits = []

    def _request(self, method, path, payload=None, params=None, auth_required=True):
        if method == "POST" and path == "/api/v3/brokerage/orders":
            self.submits.append(payload)
            return {"success": True, "success_response": {"order_id": "close-exchange-1"}}
        raise AssertionError(f"unexpected request {method} {path}")

    def get_order(self, order_id):
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": self.submits[-1]["client_order_id"],
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "FILLED",
                "filled_size": "0.00015416",
                "average_filled_price": "71000",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return [{"price": "71000", "size": "0.00015416", "commission": "0.01"}]


class _SubmitAndOpenClient(_ReadyNoSubmitClient):
    def __init__(self):
        self.submits = []

    def _request(self, method, path, payload=None, params=None, auth_required=True):
        if method == "POST" and path == "/api/v3/brokerage/orders":
            self.submits.append(payload)
            return {"success": True, "success_response": {"order_id": "close-exchange-open"}}
        raise AssertionError(f"unexpected request {method} {path}")

    def get_order(self, order_id):
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": self.submits[-1]["client_order_id"],
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "filled_size": "0",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


class _ReadOnlyOrderClient(_RejectLiveClient):
    def __init__(self, *, expected_order_id: str, status: str = "FILLED"):
        self.expected_order_id = expected_order_id
        self.status = status
        self.get_order_calls = []
        self.fill_calls = []

    def get_order(self, order_id):
        self.get_order_calls.append(order_id)
        assert order_id == self.expected_order_id
        if self.status == "FILLED":
            return {
                "order": {
                    "order_id": "41038fc6-e599-44ea-b76f-c56032570132",
                    "client_order_id": "controlled-close-BTCUSDC-bc3330fe-2T1659421771980000",
                    "product_id": "BTC-USDC",
                    "side": "SELL",
                    "status": "FILLED",
                    "filled_size": "0.00030832",
                    "average_filled_price": "63933.79",
                    "filled_value": "19.7120661328",
                    "total_fees": "0.2365447935936",
                    "total_value_after_fees": "19.4755213392064",
                    "settled": True,
                    "outstanding_hold_amount": "0",
                    "last_fill_time": "2026-06-12T16:59:42.617Z",
                }
            }
        return {
            "order": {
                "order_id": self.expected_order_id,
                "client_order_id": "controlled-close-BTCUSDC-bc3330fe-2T1659421771980000",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "filled_size": "0",
                "average_filled_price": "0",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        self.fill_calls.append(order_id)
        assert order_id == self.expected_order_id
        return []


def _seed_controlled_close(orders: OrderStore, **overrides) -> None:
    payload = {
        "client_order_id": "controlled-close-BTCUSDC-bc3330fe-2T1659421771980000",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "controlled_btc_position_close_v1",
        "linked_position_id": LINKED,
        "exchange_order_id": "41038fc6-e599-44ea-b76f-c56032570132",
        "order_id": "41038fc6-e599-44ea-b76f-c56032570132",
        "size_base": "0.00030832",
        "remaining_size": "0.00030832",
        "remaining_base": "0.00030832",
        "execution_action": "controlled_position_close_sell",
    }
    payload.update(overrides)
    orders.upsert_order(payload)


def test_no_ack_does_nothing(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, ack="", client=_RejectLiveClient())

    assert report["status"] == "ack_required_noop"
    assert report["ack_valid"] is False
    assert report["live_cancel_attempted"] is False
    assert report["live_sell_submit_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_submit"] is True


def test_open_tp_gives_cancel_first_route(tmp_path: Path, monkeypatch) -> None:
    client = _CancelOnlyClient()
    report = _report(tmp_path, monkeypatch, client=client)

    assert report["live_cancel_attempted"] is True
    assert client.cancel_calls == [STALE_EXCHANGE]
    assert report["cancel_verification"]["normalized_status"] == "cancelled"
    assert "coinbase_available_base_lookup_failed" in report["blockers"]
    assert report["live_sell_submit_attempted"] is False
    assert report["no_coinbase_submit"] is True


def test_cancel_verified_gives_stop_sell_ready(tmp_path: Path, monkeypatch) -> None:
    client = _SubmitAndOpenClient()
    report = _report(tmp_path, monkeypatch, client=client, tp_status="cancelled")

    assert report["pre_sell_status"] == "stop_sell_ready"
    assert report["cancel_verification"]["cancel_verified"] is True
    assert report["sell_sizing"]["sell_base"] == "0.00015416"
    assert report["live_sell_submit_attempted"] is True
    assert len(client.submits) == 1


def test_duplicate_sell_is_blocked(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders, status="cancelled", remaining_size="0")
    orders.upsert_order(
        {
            "client_order_id": "controlled-close-BTCUSDC-existing",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "phase": "controlled_btc_position_close_v1",
            "linked_position_id": LINKED,
            "exchange_order_id": "close-open-1",
            "order_id": "close-open-1",
            "size_base": "0.00015416",
            "remaining_size": "0.00015416",
            "execution_action": "controlled_position_close_sell",
        }
    )

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=_RejectLiveClient(),
    )

    assert report["status"] == "duplicate_sell_blocked"
    assert "duplicate_open_sell_blocks_controlled_close" in report["blockers"]
    assert report["live_sell_submit_attempted"] is False


def test_filled_sell_gives_local_apply_result(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, client=_SubmitAndFilledClient(), tp_status="cancelled")
    state = StateStore()
    position = state.get_position("BTC-USDC")

    assert report["status"] == "controlled_close_filled_reconciled"
    assert report["live_order_submitted"] is True
    assert report["fill_evidence"]["normalized_status"] == "filled"
    assert report["local_apply_result"]["status"] == "controlled_close_local_apply_performed"
    assert report["state_write_performed"] is True
    assert position["status"] == "closed"
    assert position["position_size_base"] == "0"


def test_idempotent_rerun_does_not_submit_second_sell(tmp_path: Path, monkeypatch) -> None:
    client = _SubmitAndFilledClient()
    first = _report(tmp_path, monkeypatch, client=client, tp_status="cancelled")
    second = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=_orders(tmp_path),
        state_store=StateStore(),
        coinbase_client=_RejectLiveClient(),
    )

    assert first["status"] == "controlled_close_filled_reconciled"
    assert len(client.submits) == 1
    assert second["status"] == "controlled_close_filled_reconciled"
    assert second["local_apply_result"]["status"] == "controlled_close_apply_idempotent_noop"
    assert second["live_sell_submit_attempted"] is False
    assert second["no_coinbase_submit"] is True


def test_coinbase_filled_submitted_controlled_close_reconciles_order_fields(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders, status="cancelled", remaining_size="0")
    _seed_controlled_close(orders)
    client = _ReadOnlyOrderClient(expected_order_id="41038fc6-e599-44ea-b76f-c56032570132")

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )
    order = orders.get_order("controlled-close-BTCUSDC-bc3330fe-2T1659421771980000")

    assert report["status"] == "controlled_close_filled_reconciled"
    assert report["live_sell_submit_attempted"] is False
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert client.get_order_calls == ["41038fc6-e599-44ea-b76f-c56032570132"]
    assert order["status"] == "filled"
    assert order["remaining_size"] == "0"
    assert order["remaining_base"] == "0"
    assert order["filled_base"] == "0.00030832"
    assert order["filled_quote"] == "19.7120661328"
    assert order["avg_fill_price"] == "63933.79"
    assert order["total_fees"] == "0.2365447935936"
    assert order["settled"] is True
    assert order["local_reconcile_reason"] == "coinbase_filled_controlled_btc_position_close"
    assert orders.reserved_base_by_ticker().get("BTC-USDC") is None


def test_position_already_closed_still_reconciles_open_controlled_close_order(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", bot_managed_base="0", reserved_base_open_exit_orders="0")
    _seed_tp(orders, status="cancelled", remaining_size="0")
    _seed_controlled_close(orders)
    client = _ReadOnlyOrderClient(expected_order_id="41038fc6-e599-44ea-b76f-c56032570132")

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert report["status"] == "controlled_close_filled_reconciled"
    assert orders.get_order("controlled-close-BTCUSDC-bc3330fe-2T1659421771980000")["status"] == "filled"
    assert report["live_sell_submit_attempted"] is False


def test_nested_coinbase_success_response_order_id_is_used_for_reconcile(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", bot_managed_base="0", reserved_base_open_exit_orders="0")
    _seed_tp(orders, status="cancelled", remaining_size="0")
    _seed_controlled_close(
        orders,
        exchange_order_id="",
        order_id="",
        coinbase_response={"success_response": {"order_id": "41038fc6-e599-44ea-b76f-c56032570132"}},
    )
    client = _ReadOnlyOrderClient(expected_order_id="41038fc6-e599-44ea-b76f-c56032570132")

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )

    assert report["status"] == "controlled_close_filled_reconciled"
    assert client.get_order_calls == ["41038fc6-e599-44ea-b76f-c56032570132"]


def test_repeated_reconcile_run_stays_filled_without_live_action(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", bot_managed_base="0", reserved_base_open_exit_orders="0")
    _seed_tp(orders, status="cancelled", remaining_size="0")
    _seed_controlled_close(orders)
    first_client = _ReadOnlyOrderClient(expected_order_id="41038fc6-e599-44ea-b76f-c56032570132")

    first = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=first_client,
    )
    second = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=_RejectLiveClient(),
    )

    assert first["status"] == "controlled_close_filled_reconciled"
    assert second["status"] == "controlled_close_filled_reconciled"
    assert second["local_apply_result"]["status"] == "controlled_close_apply_idempotent_noop"
    assert second["live_sell_submit_attempted"] is False
    assert second["no_coinbase_submit"] is True
    assert second["no_coinbase_cancel"] is True


def test_open_coinbase_controlled_close_without_fill_does_not_apply_local_filled(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, status="closed", position_size_base="0", bot_managed_base="0", reserved_base_open_exit_orders="0")
    _seed_tp(orders, status="cancelled", remaining_size="0")
    _seed_controlled_close(orders, filled_base="0.00030832")
    client = _ReadOnlyOrderClient(expected_order_id="41038fc6-e599-44ea-b76f-c56032570132", status="OPEN")

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=client,
    )
    order = orders.get_order("controlled-close-BTCUSDC-bc3330fe-2T1659421771980000")

    assert report["status"] == "noop_position_already_closed"
    assert report["controlled_close_reconcile"]["status"] == "no_terminal_fill_evidence"
    assert order["status"] == "submitted"
    assert order["remaining_size"] == "0.00030832"
    assert "local_reconcile_reason" not in order
    assert report["live_sell_submit_attempted"] is False
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True


def test_main_loads_config_before_coinbase_request(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    calls = []

    class _Cfg:
        coinbase_api_host = "api.coinbase.com"
        coinbase_timeout_seconds = 15

    class _Client(_CancelOnlyClient):
        def cancel_order(self, order_id):
            calls.append("cancel")
            return super().cancel_order(order_id)

    def _load_config():
        calls.append("config")
        return {
            "cfg": _Cfg(),
            "metadata": {
                "project_dotenv_loaded": True,
                "coinbase_credential_presence": {
                    "COINBASE_API_KEY": "set",
                    "COINBASE_API_SECRET": "set",
                },
                "credential_scheme": "coinbase_cdp_jwt_env",
                "coinbase_credentials_ready": True,
                "bot_config_loaded": True,
            },
        }

    def _client_factory(*args, **kwargs):
        calls.append("client")
        return _Client()

    out = tmp_path / "report.json"
    monkeypatch.setattr(close_tool, "_load_bot_config_for_coinbase_auth", _load_config)
    monkeypatch.setattr(close_tool, "CoinbaseClient", _client_factory)
    monkeypatch.setattr(
        close_tool.sys,
        "argv",
        [
            "execute_controlled_btc_position_close.py",
            "--ticker",
            "BTC-USDC",
            "--linked-position-id",
            LINKED,
            "--stale-tp-client-order-id",
            STALE_CLIENT,
            "--stale-tp-exchange-order-id",
            STALE_EXCHANGE,
            "--ack",
            ACK,
            "--json-out",
            str(out),
        ],
    )

    rc = close_tool.main()
    report = json.loads(out.read_text())

    assert rc == 2
    assert calls[:3] == ["config", "client", "cancel"]
    assert report["project_dotenv_loaded"] is True
    assert report["coinbase_credential_presence"] == {
        "COINBASE_API_KEY": "set",
        "COINBASE_API_SECRET": "set",
    }
    assert report["credential_scheme"] == "coinbase_cdp_jwt_env"


def test_missing_credentials_after_config_load_blocks_before_live_calls(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)

    report = build_controlled_position_close_report(
        ticker="BTC-USDC",
        linked_position_id=LINKED,
        stale_tp_client_order_id=STALE_CLIENT,
        stale_tp_exchange_order_id=STALE_EXCHANGE,
        order_type="near_market_limit_ioc",
        ack=ACK,
        order_store=orders,
        state_store=state,
        coinbase_client=_RejectLiveClient(),
        credential_context={
            "project_dotenv_loaded": False,
            "coinbase_credential_presence": {
                "COINBASE_API_KEY": "missing",
                "COINBASE_API_SECRET": "missing",
            },
            "credential_scheme": "coinbase_cdp_jwt_env",
            "coinbase_credentials_ready": False,
            "bot_config_loaded": False,
        },
    )

    assert report["status"] == "credential_load_failed"
    assert report["blocker"] == "coinbase_credentials_missing_after_config_load"
    assert report["live_cancel_attempted"] is False
    assert report["live_sell_submit_attempted"] is False
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_submit"] is True


def test_main_without_ack_does_not_load_config_or_live_client(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)

    def _unexpected_config_load():
        raise AssertionError("config load must not be required without ACK")

    def _unexpected_client(*args, **kwargs):
        raise AssertionError("Coinbase client must not be created without ACK")

    out = tmp_path / "report.json"
    monkeypatch.setattr(close_tool, "_load_bot_config_for_coinbase_auth", _unexpected_config_load)
    monkeypatch.setattr(close_tool, "CoinbaseClient", _unexpected_client)
    monkeypatch.setattr(
        close_tool.sys,
        "argv",
        [
            "execute_controlled_btc_position_close.py",
            "--ticker",
            "BTC-USDC",
            "--linked-position-id",
            LINKED,
            "--stale-tp-client-order-id",
            STALE_CLIENT,
            "--stale-tp-exchange-order-id",
            STALE_EXCHANGE,
            "--json-out",
            str(out),
        ],
    )

    rc = close_tool.main()
    report = json.loads(out.read_text())

    assert rc == 2
    assert report["status"] == "ack_required_noop"
    assert report["live_cancel_attempted"] is False
    assert report["live_sell_submit_attempted"] is False
