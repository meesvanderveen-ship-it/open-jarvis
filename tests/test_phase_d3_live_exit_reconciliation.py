from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_live_exit_reconciliation import (
    D3_LIVE_EXIT_RECONCILE_ACK,
    reconcile_phase_d3_live_exit_order,
)
from bot.state_store import StateStore


def _seed_position(store: StateStore) -> None:
    store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.10",
        position_size_quote="8000",
        extra={
            "bot_managed_base": "0.10",
            "status": "open",
        },
    )


def _seed_live_exit(store: OrderStore, *, status: str = "submitted") -> None:
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": status,
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "exchange_order_id": "cb-order-1",
        "order_id": "cb-order-1",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.04",
        "remaining_size": "0.04",
        "limit_price": "81664.97",
    })


def _snapshot(
    normalized_status: str,
    *,
    filled_base: str = "0",
    filled_quote: str = "0",
    avg_fill_price: str = "0",
    fill_count: int = 0,
    fees: str = "0",
) -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": normalized_status.upper(),
        "normalized_status": normalized_status,
        "filled_base": filled_base,
        "filled_quote": filled_quote,
        "avg_fill_price": avg_fill_price,
        "fill_count": fill_count,
        "fees": fees,
        "liquidity": [],
    }


def _run(tmp_path: Path, monkeypatch, *, snapshot: dict, apply: bool = False, apply_ack: str = "") -> dict:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)
    return reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=apply,
        apply_ack=apply_ack,
    )


def test_open_snapshot_dry_run_keeps_order_open(monkeypatch, tmp_path: Path):
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("open"))
    assert report["status"] == "d3_live_exit_reconcile_keep_open"
    assert report["suggested_action"] == "keep_open"
    assert report["no_state_write"] is True
    assert report["blockers"] == []


def test_d3_open_keep_open_preserves_order_counts_and_position_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    before_counts = order_store.open_order_counts()
    before_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    before_position = state_store.get_position("BTC-USDC")

    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("open"),
        order_store=order_store,
        state_store=state_store,
    )

    after_counts = order_store.open_order_counts()
    after_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    after_position = state_store.get_position("BTC-USDC")

    assert before_counts == after_counts
    assert before_order == after_order
    assert before_position == after_position
    assert report["no_state_write"] is True
    assert report["proposed_order_updates"] == {}
    assert report["proposed_position_updates"] == {}
    assert report["suggested_action"] == "keep_open"
    assert report["status"] == "d3_live_exit_reconcile_keep_open"


def test_open_snapshot_apply_is_blocked(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("open"),
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    assert report["status"] == "d3_live_exit_reconcile_apply_blocked"
    assert "d3_reconcile_open_order_no_apply_needed" in report["blockers"]


def test_d3_unknown_network_failure_never_proposes_apply_or_trading_action(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot={
            "coinbase_call_attempted": True,
            "coinbase_call_succeeded": False,
            "raw_status": "",
            "normalized_status": "unknown",
            "filled_base": "0",
            "filled_quote": "0",
            "avg_fill_price": "0",
            "fill_count": 0,
            "fees": "0",
            "liquidity": [],
        },
    )
    assert report["status"] == "d3_live_exit_reconcile_blocked"
    assert report["suggested_action"] == "unknown_no_apply"
    assert "coinbase_snapshot_unavailable" in report["blockers"]
    assert "coinbase_snapshot_status_unknown_or_unsupported" in report["blockers"]
    assert report["proposed_order_updates"] == {}
    assert report["proposed_position_updates"] == {}
    assert report["no_state_write"] is True
    assert not report["status"].endswith("_ready")
    assert not report["status"].endswith("_applied")
    assert report["suggested_action"] not in {"keep_open", "mark_partially_filled", "mark_filled", "mark_cancelled", "mark_rejected", "mark_expired"}


def test_rejected_snapshot_dry_run_proposes_rejected(monkeypatch, tmp_path: Path):
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("rejected"))
    assert report["status"] == "d3_live_exit_reconcile_rejected_ready"
    assert report["proposed_order_updates"]["status"] == "rejected"
    assert report["proposed_order_updates"]["remaining_size"] == "0"
    assert report["proposed_position_updates"]["last_d3_reconcile_status"] == "rejected"


def test_rejected_apply_requires_ack(monkeypatch, tmp_path: Path):
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("rejected"), apply=True)
    assert "d3_live_exit_reconcile_apply_ack_required" in report["blockers"]


def test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    pre_closeout_position = state_store.get_position("BTC-USDC")
    dry_run = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("rejected"),
        order_store=order_store,
        state_store=state_store,
    )

    assert dry_run["status"] == "d3_live_exit_reconcile_rejected_ready"
    assert dry_run["suggested_action"] == "mark_rejected"
    assert dry_run["proposed_order_updates"]["status"] == "rejected"
    assert dry_run["proposed_order_updates"]["remaining_size"] == "0"
    assert dry_run["proposed_position_updates"]["last_d3_reconcile_status"] == "rejected"
    assert "position_size_base" not in dry_run["proposed_position_updates"]
    assert "bot_managed_base" not in dry_run["proposed_position_updates"]
    assert "last_d3_reconcile_fill_delta_base" not in dry_run["proposed_position_updates"]
    assert "filled" not in dry_run["status"]
    assert "cancel" not in dry_run["status"]
    assert "replace" not in dry_run["status"]
    assert "retry" not in dry_run["status"]

    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("rejected"),
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )

    local_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    position = state_store.get_position("BTC-USDC")

    assert report["status"] == "d3_live_exit_reconcile_rejected_applied"
    assert report["suggested_action"] == "mark_rejected"
    assert report["blockers"] == []
    assert report["no_state_write"] is False
    assert report["proposed_order_updates"]["status"] == "rejected"
    assert report["proposed_order_updates"]["remaining_size"] == "0"
    assert report["proposed_position_updates"]["last_d3_reconcile_status"] == "rejected"
    assert "position_size_base" not in report["proposed_position_updates"]
    assert "bot_managed_base" not in report["proposed_position_updates"]
    assert "last_d3_reconcile_fill_delta_base" not in report["proposed_position_updates"]
    assert local_order["status"] == "rejected"
    assert local_order["remaining_size"] == "0"
    assert local_order["finalized_at"]
    assert local_order["closed_at"]
    assert local_order["rejected_at"]
    assert order_store.open_exit_orders("BTC-USDC") == []
    assert order_store.reserved_base_by_ticker().get("BTC-USDC") in {None, "0"}
    assert position["position_size_base"] == pre_closeout_position["position_size_base"]
    assert position["bot_managed_base"] == pre_closeout_position["bot_managed_base"]
    assert position["status"] == "open"
    assert float(position["position_size_base"]) >= 0
    assert float(position["bot_managed_base"]) >= 0
    assert report["suggested_action"] not in {"keep_open", "mark_filled", "mark_partially_filled", "mark_cancelled", "mark_expired"}
    assert "sell" not in report["status"]
    assert "replace" not in report["status"]
    assert "retry" not in report["status"]


def test_cancelled_snapshot_dry_run_proposes_cancelled(monkeypatch, tmp_path: Path):
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("cancelled"))
    assert report["status"] == "d3_live_exit_reconcile_cancelled_ready"
    assert report["proposed_order_updates"]["status"] == "cancelled"
    assert report["proposed_order_updates"]["remaining_size"] == "0"


def test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    pre_closeout_position = state_store.get_position("BTC-USDC")
    dry_run = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("cancelled"),
        order_store=order_store,
        state_store=state_store,
    )

    assert dry_run["status"] == "d3_live_exit_reconcile_cancelled_ready"
    assert dry_run["suggested_action"] == "mark_cancelled"
    assert dry_run["proposed_order_updates"]["status"] == "cancelled"
    assert dry_run["proposed_order_updates"]["remaining_size"] == "0"

    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("cancelled"),
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )

    local_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    position = state_store.get_position("BTC-USDC")

    assert report["status"] == "d3_live_exit_reconcile_cancelled_applied"
    assert report["suggested_action"] == "mark_cancelled"
    assert report["blockers"] == []
    assert report["no_state_write"] is False
    assert report["proposed_order_updates"]["status"] == "cancelled"
    assert report["proposed_order_updates"]["remaining_size"] == "0"
    assert report["proposed_position_updates"]["last_d3_reconcile_status"] == "cancelled"
    assert local_order["status"] == "cancelled"
    assert local_order["remaining_size"] == "0"
    assert local_order["finalized_at"]
    assert local_order["closed_at"]
    assert local_order["cancelled_at"]
    assert order_store.open_exit_orders("BTC-USDC") == []
    assert order_store.reserved_base_by_ticker().get("BTC-USDC") in {None, "0"}
    assert position["position_size_base"] == pre_closeout_position["position_size_base"]
    assert position["bot_managed_base"] == pre_closeout_position["bot_managed_base"]
    assert position["status"] == "open"
    assert float(position["position_size_base"]) >= 0
    assert float(position["bot_managed_base"]) >= 0
    assert report["suggested_action"] not in {"keep_open", "mark_filled", "mark_partially_filled", "mark_rejected", "mark_expired"}
    assert "sell" not in report["status"]
    assert "replace" not in report["status"]
    assert "retry" not in report["status"]


def test_expired_snapshot_dry_run_proposes_expired(monkeypatch, tmp_path: Path):
    report = _run(tmp_path, monkeypatch, snapshot=_snapshot("expired"))
    assert report["status"] == "d3_live_exit_reconcile_expired_ready"
    assert report["proposed_order_updates"]["status"] == "expired"


def test_expired_apply_marks_terminal_without_position_size_change(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    before_position = state_store.get_position("BTC-USDC")
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("expired"),
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )

    local_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    after_position = state_store.get_position("BTC-USDC")

    assert report["status"] == "d3_live_exit_reconcile_expired_applied"
    assert report["suggested_action"] == "mark_expired"
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert local_order["status"] == "expired"
    assert local_order["remaining_size"] == "0"
    assert local_order["finalized_at"]
    assert local_order["closed_at"]
    assert local_order["expired_at"]
    assert order_store.open_exit_orders("BTC-USDC") == []
    assert order_store.reserved_base_by_ticker().get("BTC-USDC") in {None, "0"}
    assert after_position["position_size_base"] == before_position["position_size_base"]
    assert after_position["bot_managed_base"] == before_position["bot_managed_base"]
    assert after_position["status"] == "open"
    assert "sell" not in report["status"]
    assert "replace" not in report["status"]
    assert "retry" not in report["status"]


def test_partial_fill_dry_run_reduces_only_filled_delta(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot(
            "partially_filled",
            filled_base="0.01",
            filled_quote="820",
            avg_fill_price="82000",
            fill_count=1,
            fees="0.25",
        ),
    )
    assert report["status"] == "d3_live_exit_reconcile_partially_filled_ready"
    assert report["proposed_order_updates"]["status"] == "partially_filled"
    assert report["proposed_order_updates"]["remaining_size"] == "0.03"
    assert report["proposed_position_updates"]["position_size_base"] == "0.06"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.09"
    assert report["proposed_position_updates"]["last_d3_reconcile_fill_delta_base"] == "0.01"


def test_full_fill_dry_run_releases_reservation_and_marks_tp1_complete(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot(
            "filled",
            filled_base="0.04",
            filled_quote="3266.5988",
            avg_fill_price="81664.97",
            fill_count=1,
            fees="0.40",
        ),
    )
    assert report["status"] == "d3_live_exit_reconcile_filled_ready"
    assert report["proposed_order_updates"]["status"] == "filled"
    assert report["proposed_order_updates"]["remaining_size"] == "0"
    assert report["proposed_position_updates"]["position_size_base"] == "0.06"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.06"
    assert "d3_tp1_completed_at" in report["proposed_position_updates"]


def test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    state_store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.06",
        position_size_quote="4800",
        extra={"bot_managed_base": "0.10", "status": "open"},
    )
    _seed_live_exit(order_store)

    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot(
            "filled",
            filled_base="0.04",
            filled_quote="3266.5988",
            avg_fill_price="81664.97",
            fill_count=1,
        ),
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )

    local_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    position = state_store.get_position("BTC-USDC")

    assert report["status"] == "d3_live_exit_reconcile_filled_applied"
    assert report["suggested_action"] == "mark_filled"
    assert report["blockers"] == []
    assert report["no_state_write"] is False
    assert report["proposed_order_updates"]["status"] == "filled"
    assert report["proposed_order_updates"]["remaining_size"] == "0"
    assert report["proposed_position_updates"]["position_size_base"] == "0.06"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.06"
    assert report["proposed_position_updates"]["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0"
    assert report["proposed_position_updates"]["last_d3_reconcile_total_managed_base_before_fill"] == "0.10"
    assert "d3_tp1_completed_at" in report["proposed_position_updates"]
    assert local_order["status"] == "filled"
    assert local_order["remaining_size"] == "0"
    assert local_order["finalized_at"]
    assert local_order["closed_at"]
    assert local_order["filled_at"]
    assert position["position_size_base"] == "0.06"
    assert position["bot_managed_base"] == "0.06"
    assert position["status"] == "open"
    assert "close_time" not in position
    assert "close_reason" not in position
    assert position["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0"
    assert position["last_d3_reconcile_total_managed_base_before_fill"] == "0.10"
    assert position["last_d3_reconcile_status"] == "filled"
    assert order_store.open_exit_orders("BTC-USDC") == []
    assert order_store.reserved_base_by_ticker().get("BTC-USDC") in {None, "0"}
    assert float(position["position_size_base"]) >= 0
    assert float(position["bot_managed_base"]) >= 0
    assert report["suggested_action"] not in {"keep_open", "mark_partially_filled", "mark_cancelled", "mark_rejected", "mark_expired"}
    assert "cancel" not in report["status"]
    assert "replace" not in report["status"]
    assert "retry" not in report["status"]


def test_apply_partial_fill_updates_order_and_position(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("partially_filled", filled_base="0.01", filled_quote="820", avg_fill_price="82000", fill_count=1),
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    assert report["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    local_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    assert local_order["status"] == "partially_filled"
    assert local_order["remaining_size"] == "0.03"
    position = state_store.get_position("BTC-USDC")
    assert position["position_size_base"] == "0.06"
    assert position["bot_managed_base"] == "0.09"


def test_apply_is_idempotent_for_already_applied_partial(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)
    snapshot = _snapshot("partially_filled", filled_base="0.01", filled_quote="820", avg_fill_price="82000", fill_count=1)
    first = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    second = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    assert first["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    assert second["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    position = state_store.get_position("BTC-USDC")
    assert position["position_size_base"] == "0.06"
    assert position["bot_managed_base"] == "0.09"


def test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    first_snapshot = _snapshot(
        "partially_filled",
        filled_base="0.01",
        filled_quote="820",
        avg_fill_price="82000",
        fill_count=1,
        fees="0.25",
    )
    second_snapshot = _snapshot(
        "partially_filled",
        filled_base="0.025",
        filled_quote="2050",
        avg_fill_price="82000",
        fill_count=2,
        fees="0.40",
    )

    first = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=first_snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    first_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    first_position = state_store.get_position("BTC-USDC")

    second = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=second_snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    second_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    second_position = state_store.get_position("BTC-USDC")

    repeated_second = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=second_snapshot,
        order_store=order_store,
        state_store=state_store,
        apply=True,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK,
    )
    repeated_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    repeated_position = state_store.get_position("BTC-USDC")

    assert first["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    assert first["suggested_action"] == "mark_partially_filled"
    assert first["applied_order"]["last_fill_delta_base"] == "0.01"
    assert first["applied_order"]["remaining_size"] == "0.03"
    assert first["applied_position"]["position_size_base"] == "0.06"
    assert first["applied_position"]["bot_managed_base"] == "0.09"
    assert first["applied_position"]["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0.03"
    assert first_order["status"] == "partially_filled"
    assert first_order["remaining_size"] == "0.03"
    assert first_position["position_size_base"] == "0.06"
    assert first_position["bot_managed_base"] == "0.09"

    assert second["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    assert second["suggested_action"] == "mark_partially_filled"
    assert second["applied_order"]["last_fill_delta_base"] == "0.015"
    assert second["applied_order"]["remaining_size"] == "0.015"
    assert second["applied_order"]["filled_size"] == "0.025"
    assert second["applied_order"]["filled_quote_value"] == "2050"
    assert second["applied_order"]["avg_fill_price"] == "82000"
    assert second["applied_order"]["fill_count"] == 2
    assert second["applied_position"]["position_size_base"] == "0.060"
    assert second["applied_position"]["bot_managed_base"] == "0.075"
    assert second["applied_position"]["last_d3_reconcile_fill_delta_base"] == "0.015"
    assert second["applied_position"]["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0.015"
    assert second_order["status"] == "partially_filled"
    assert second_order["remaining_size"] == "0.015"
    assert second_position["position_size_base"] == "0.060"
    assert second_position["bot_managed_base"] == "0.075"

    assert repeated_second["status"] == "d3_live_exit_reconcile_partially_filled_applied"
    assert repeated_second["suggested_action"] == "mark_partially_filled"
    assert repeated_second["applied_order"]["last_fill_delta_base"] == "0.000"
    assert repeated_second["applied_order"]["remaining_size"] == "0.015"
    assert repeated_second["applied_position"]["position_size_base"] == "0.060"
    assert repeated_second["applied_position"]["bot_managed_base"] == "0.075"
    assert repeated_order["remaining_size"] == "0.015"
    assert repeated_position["position_size_base"] == "0.060"
    assert repeated_position["bot_managed_base"] == "0.075"
    assert float(repeated_position["position_size_base"]) >= 0
    assert float(repeated_position["bot_managed_base"]) >= 0
    assert order_store.open_exit_orders("BTC-USDC")
    assert len(order_store.open_exit_orders("BTC-USDC")) == 1
    assert order_store.open_exit_orders("BTC-USDC")[0]["client_order_id"] == "phased3-BTCUSDC-TP1-pos-1"
    assert order_store.open_exit_orders("BTC-USDC")[0]["remaining_size"] == "0.015"
    assert repeated_second["suggested_action"] not in {"mark_filled", "mark_cancelled", "mark_rejected", "mark_expired", "keep_open"}
    assert "replace" not in repeated_second["status"]
    assert "retry" not in repeated_second["status"]
    assert "cancel" not in repeated_second["status"]


def test_order_id_mismatch_blocks(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="1000"),
    )
    monkeypatch.chdir(tmp_path)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="wrong-order-id",
        linked_position_id="pos-1",
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="1000"),
        order_store=order_store,
        state_store=state_store,
    )
    assert "local_d3_order_not_found" in report["blockers"] or "exchange_order_id_mismatch" in report["blockers"]


def test_linked_position_mismatch_blocks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="other-pos",
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="1000"),
        order_store=order_store,
        state_store=state_store,
    )
    assert "linked_position_id_mismatch" in report["blockers"]


def test_duplicate_d3_order_blocks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)
    order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-dup",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "exchange_order_id": "cb-order-dup",
        "order_id": "cb-order-dup",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.01",
        "remaining_size": "0.01",
    })
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="1000"),
        order_store=order_store,
        state_store=state_store,
    )
    assert "duplicate_open_d3_exit_order_for_position_and_label" in report["blockers"]


def test_filled_base_exceeds_order_size_blocks(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot=_snapshot("filled", filled_base="0.05", filled_quote="1000"),
    )
    assert "filled_base_exceeds_order_size" in report["blockers"]


def test_filled_base_exceeds_position_base_blocks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    state_store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.01",
        position_size_quote="800",
        extra={"bot_managed_base": "0.01", "status": "open"},
    )
    _seed_live_exit(order_store)
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="1000"),
        order_store=order_store,
        state_store=state_store,
    )
    assert "filled_base_exceeds_total_managed_base" in report["blockers"]


def test_unknown_snapshot_blocks(monkeypatch, tmp_path: Path):
    report = _run(
        tmp_path,
        monkeypatch,
        snapshot={"coinbase_call_attempted": True, "coinbase_call_succeeded": False, "normalized_status": "unknown"},
    )
    assert "coinbase_snapshot_unavailable" in report["blockers"]


def test_full_fill_allowed_when_position_base_is_available_only(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    state_store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.06",
        position_size_quote="4800",
        extra={"bot_managed_base": "0.10", "status": "open"},
    )
    _seed_live_exit(order_store)
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("filled", filled_base="0.04", filled_quote="3266.5988", avg_fill_price="81664.97", fill_count=1),
        order_store=order_store,
        state_store=state_store,
    )
    assert report["status"] == "d3_live_exit_reconcile_filled_ready"
    assert report["blockers"] == []
    assert report["proposed_position_updates"]["position_size_base"] == "0.06"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.06"
    assert report["proposed_position_updates"]["last_d3_reconcile_total_managed_base_before_fill"] == "0.10"
    assert report["proposed_position_updates"]["last_d3_reconcile_reserved_base_this_exit_before_fill"] == "0.04"
    assert report["proposed_position_updates"]["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0"


def test_partial_fill_allowed_when_position_base_is_available_only(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    state_store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.06",
        position_size_quote="4800",
        extra={"bot_managed_base": "0.10", "status": "open"},
    )
    _seed_live_exit(order_store)
    report = reconcile_phase_d3_live_exit_order(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot=_snapshot("partially_filled", filled_base="0.01", filled_quote="820", avg_fill_price="82000", fill_count=1),
        order_store=order_store,
        state_store=state_store,
    )
    assert report["status"] == "d3_live_exit_reconcile_partially_filled_ready"
    assert report["blockers"] == []
    assert report["proposed_order_updates"]["remaining_size"] == "0.03"
    assert report["proposed_position_updates"]["position_size_base"] == "0.06"
    assert report["proposed_position_updates"]["bot_managed_base"] == "0.09"
    assert report["proposed_position_updates"]["last_d3_reconcile_fill_delta_base"] == "0.01"
    assert report["proposed_position_updates"]["last_d3_reconcile_reserved_base_this_exit_after_fill"] == "0.03"
