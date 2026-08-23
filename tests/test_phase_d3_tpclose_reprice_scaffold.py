from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d3_tpclose_reprice_scaffold import (
    TPCLOSE_REPRICE_ACK,
    build_phase_d3_tpclose_reprice_scaffold_report,
)
from bot.state_store import StateStore


def _cfg():
    return SimpleNamespace(
        enable_phase_d3_actual_exit_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
    )


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = StateStore()
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "open",
            "order_id": "pos-1",
            "position_size_base": "0.0000649067431275",
            "bot_managed_base": "0.0000649067431275",
            "reserved_base_open_exit_orders": "0.00006490",
        },
    )
    return state


def _orders(tmp_path: Path) -> OrderStore:
    store = OrderStore(path=tmp_path / "state" / "open_orders.json", log_path=tmp_path / "logs" / "order_events.jsonl")
    store.upsert_order(
        {
            "client_order_id": "old-client",
            "exchange_order_id": "old-exchange",
            "order_id": "old-exchange",
            "ticker": "BTC-USDC",
            "product_id": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "d3_exit_label": "TP_CLOSE",
            "linked_position_id": "pos-1",
            "execution_action": "place_limit_sell",
            "remaining_size": "0.00006490",
            "size_base": "0.00006490",
            "limit_price": "84800.00",
            "post_only": True,
        },
        event_type="seed_order",
    )
    return store


def _snapshot(status="open", filled="0"):
    return {
        "normalized_status": status,
        "raw_status": status.upper(),
        "filled_base": filled,
        "filled_quote": "0",
        "fill_count": 0 if filled == "0" else 1,
        "remaining_size": "0.00006490",
    }


class FakeClient:
    def __init__(self, *, cancel_response=None, cancel_exc=None, replace_response=None):
        self.cancel_response = cancel_response if cancel_response is not None else {"success": True, "order_ids": ["old-exchange"]}
        self.cancel_exc = cancel_exc
        self.replace_response = replace_response if replace_response is not None else {"success": True, "success_response": {"order_id": "new-exchange"}}
        self.cancelled = []
        self.placed = []

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        if self.cancel_exc:
            raise self.cancel_exc
        return self.cancel_response

    def get_order(self, order_id):
        return {
            "order": {
                "order_id": order_id,
                "status": "CANCELLED",
                "filled_size": "0",
                "filled_value": "0",
                "average_filled_price": "0",
                "number_of_fills": "0",
                "product_id": "BTC-USDC",
                "side": "SELL",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []

    def get_product(self, ticker):
        return {
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
            "quote_increment": "0.01",
        }

    def get_spot_position(self, ticker):
        return {"available_base_balance": "0.0000649067431275"}

    def place_limit_order(self, **kwargs):
        self.placed.append(dict(kwargs))
        return self.replace_response


def _report(tmp_path, monkeypatch, **overrides):
    params = {
        "cfg": _cfg(),
        "ticker": "BTC-USDC",
        "client_order_id": "old-client",
        "exchange_order_id": "old-exchange",
        "linked_position_id": "pos-1",
        "new_limit_price": "74000.00",
        "state_store": _state(tmp_path, monkeypatch),
        "order_store": _orders(tmp_path),
        "old_snapshot": _snapshot(),
        "confirm_label": "TP_CLOSE",
    }
    params.update(overrides)
    return build_phase_d3_tpclose_reprice_scaffold_report(**params)


def test_dry_run_ready_no_writes(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch)
    assert report["status"] == "tpclose_reprice_scaffold_ready_for_ack"
    assert report["state_write_performed"] is False
    assert report["coinbase_write_performed"] is False
    assert report["replacement_size_base"] == "0.00006490"
    assert report["replacement_estimated_quote"] == "4.8026000000"


def test_missing_ack_blocks_live_before_client_writes(tmp_path, monkeypatch):
    client = FakeClient()
    report = _report(tmp_path, monkeypatch, submit_live=True, coinbase_client=client)
    assert report["status"] == "tpclose_reprice_scaffold_ack_required"
    assert report["blockers"] == ["reprice_ack_missing_or_invalid"]
    assert client.cancelled == []
    assert client.placed == []


def test_terminal_or_filled_snapshot_blocks_cancel_replace(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, old_snapshot=_snapshot("filled", filled="0.00006490"))
    assert any(item.startswith("old_order_not_open") for item in report["blockers"])
    assert "old_order_has_fill_evidence" in report["blockers"]


def test_confirm_label_required(tmp_path, monkeypatch):
    report = _report(tmp_path, monkeypatch, confirm_label="TP1")
    assert "confirm_label_tp_close_required" in report["blockers"]


def test_cancel_failure_stops_before_replace(tmp_path, monkeypatch):
    client = FakeClient(cancel_exc=RuntimeError("cancel boom"))
    report = _report(
        tmp_path,
        monkeypatch,
        submit_live=True,
        reprice_ack=TPCLOSE_REPRICE_ACK,
        coinbase_client=client,
    )
    assert report["status"] == "tpclose_reprice_cancel_failed_no_replace"
    assert client.cancelled == ["old-exchange"]
    assert client.placed == []


def test_successful_fake_cancel_replace_updates_local_state(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    client = FakeClient()
    report = build_phase_d3_tpclose_reprice_scaffold_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        client_order_id="old-client",
        exchange_order_id="old-exchange",
        linked_position_id="pos-1",
        new_limit_price="74000.00",
        state_store=state,
        order_store=orders,
        coinbase_client=client,
        old_snapshot=_snapshot(),
        submit_live=True,
        reprice_ack=TPCLOSE_REPRICE_ACK,
        confirm_label="TP_CLOSE",
    )

    assert report["status"] == "tpclose_reprice_replacement_submitted"
    assert report["cancel_succeeded"] is True
    assert report["replace_succeeded"] is True
    assert client.cancelled == ["old-exchange"]
    assert len(client.placed) == 1
    assert client.placed[0]["limit_price"].to_eng_string() == "74000.00"
    assert orders.get_order("old-client")["status"] == "cancelled"
    assert orders.get_order(report["replacement_client_order_id"])["status"] == "submitted"
    assert state.get_position("BTC-USDC")["reserved_base_open_exit_orders"] == "0.00006490"
