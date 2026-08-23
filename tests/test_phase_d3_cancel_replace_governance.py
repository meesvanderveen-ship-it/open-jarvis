from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.order_store import OrderStore
from bot.state_store import StateStore
from tools.show_phase_d3_cancel_replace_governance import build_report


def _seed_position(
    store: StateStore,
    *,
    status: str = "open",
    position_size_base: str = "0.06000000",
    bot_managed_base: str = "0.10000000",
) -> None:
    store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base=position_size_base,
        position_size_quote="4800",
        extra={
            "bot_managed_base": bot_managed_base,
            "status": status,
        },
    )


def _seed_live_exit(
    store: OrderStore,
    *,
    client_order_id: str = "phased3-BTCUSDC-TP1-pos-1",
    exchange_order_id: str = "cb-order-1",
    remaining_size: str = "0.04000000",
    linked_position_id: str = "pos-1",
    created_at: str | None = None,
) -> None:
    store.upsert_order({
        "client_order_id": client_order_id,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": linked_position_id,
        "exchange_order_id": exchange_order_id,
        "order_id": exchange_order_id,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.04000000",
        "remaining_size": remaining_size,
        "limit_price": "81664.97",
        "created_at": created_at or (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat(),
    })


def _snapshot(
    status: str = "open",
    *,
    filled_base: str = "0",
    pending_cancel: bool = False,
) -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": filled_base,
        "filled_quote": "0",
        "remaining_size": "0.04000000",
        "fill_count": 0,
        "snapshot": {
            "raw_order": {
                "pending_cancel": pending_cancel,
            }
        },
    }


def _market() -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "best_bid": "78000.00",
        "best_ask": "78010.00",
        "mid_price": "78005.00",
    }


def _product() -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "base_increment": "0.00000001",
        "price_increment": "0.01",
        "quote_increment": "0.01",
        "min_order_quote": "1",
    }


def _build(
    tmp_path: Path,
    monkeypatch,
    *,
    snapshot: dict | None = None,
    position_status: str = "open",
    extra_open_order: bool = False,
    linked_position_id: str = "pos-1",
    bot_managed_base: str = "0.10000000",
    position_size_base: str = "0.06000000",
    created_at: str | None = None,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(
        state_store,
        status=position_status,
        position_size_base=position_size_base,
        bot_managed_base=bot_managed_base,
    )
    _seed_live_exit(order_store, linked_position_id=linked_position_id, created_at=created_at)
    if extra_open_order:
        _seed_live_exit(
            order_store,
            client_order_id="phased3-BTCUSDC-TP1-pos-1-extra",
            exchange_order_id="cb-order-2",
            remaining_size="0.01000000",
            linked_position_id="pos-1",
            created_at=created_at,
        )
    return build_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot_override=snapshot or _snapshot(),
        market_override=_market(),
        product_rules_override=_product(),
        order_store=order_store,
        state_store=state_store,
    )


def test_open_no_fills_replace_candidate_preview_available(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch)
    assert report["current_order_status"] == "open"
    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_replace_candidate_preview_only"
    assert report["cancel_candidate_preview_only"] is True
    assert report["replace_candidate_preview_only"] is True


def test_d3_cancel_replace_governance_preview_candidate_requires_cancel_first_closeout(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    before_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    before_open_ids = [order["client_order_id"] for order in order_store.open_exit_orders("BTC-USDC")]

    report = build_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot_override=_snapshot(),
        market_override=_market(),
        product_rules_override=_product(),
        order_store=order_store,
        state_store=state_store,
    )

    after_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    after_open_ids = [order["client_order_id"] for order in order_store.open_exit_orders("BTC-USDC")]
    sequence = report.get("safe_sequence_steps") or []

    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_replace_candidate_preview_only"
    assert report["replace_candidate_preview_only"] is True
    assert report["cancel_candidate_preview_only"] is True
    assert report["no_state_write"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_submit"] is True
    assert report["safety_policy"]["preview_only_governance"] is True
    assert report["required_future_cancel_ack"]
    assert report["required_future_replace_ack"]
    assert report["blockers"] == []
    assert before_order == after_order
    assert before_open_ids == after_open_ids == ["phased3-BTCUSDC-TP1-pos-1"]

    # These ordered preview steps prove there is no atomic cancel+replace path.
    assert sequence[0] == "future controlled cancel existing D.3 order"
    assert "governed local D.3 closeout and reservation release" in sequence
    assert sequence[-1] == "only then optional one-shot new SELL with ACKs"


def test_d3_cancel_replace_governance_blocks_when_replication_enabled(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("REPLICATION_ENABLED", "true")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store)

    before_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    before_open_ids = [order["client_order_id"] for order in order_store.open_exit_orders("BTC-USDC")]

    report = build_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot_override=_snapshot(),
        market_override=_market(),
        product_rules_override=_product(),
        order_store=order_store,
        state_store=state_store,
    )

    after_order = order_store.get_order("phased3-BTCUSDC-TP1-pos-1")
    after_open_ids = [order["client_order_id"] for order in order_store.open_exit_orders("BTC-USDC")]

    assert report["replication_enabled"] is True
    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_blocked_replication_enabled"
    assert "replication_enabled_blocks_d3_cancel_replace_governance" in report["blockers"]
    assert "replication_follower_must_not_control_master_d3_lifecycle" in report["warnings"]
    assert report["cancel_candidate_preview_only"] is False
    assert report["replace_candidate_preview_only"] is False
    assert report["no_state_write"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_submit"] is True
    assert report["safety_policy"]["replication_isolation_required"] is True
    assert report["safe_sequence_steps"] == []
    assert before_order == after_order
    assert before_open_ids == after_open_ids == ["phased3-BTCUSDC-TP1-pos-1"]


def test_open_with_fills_blocks_cancel_replace_and_requires_reconcile(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch, snapshot=_snapshot("open", filled_base="0.01000000"))
    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_reconcile_first"
    assert "filled_base_nonzero_reconcile_first" in report["blockers"]


def test_pending_cancel_only_monitors(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch, snapshot=_snapshot("open", pending_cancel=True))
    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_monitor_pending_cancel"
    assert "order_pending_cancel_monitor_only" in report["blockers"]


def test_terminal_status_blocks_and_requires_reconcile(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch, snapshot=_snapshot("filled"))
    assert report["cancel_replace_governance_status"] == "d3_cancel_replace_governance_reconcile_first"
    assert "order_not_open_reconcile_first" in report["blockers"]


def test_multiple_open_d3_orders_block(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch, extra_open_order=True)
    assert "open_d3_order_count_not_one" in report["blockers"]


def test_linked_position_mismatch_blocks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store)
    _seed_live_exit(order_store, linked_position_id="other-pos")
    report = build_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        snapshot_override=_snapshot(),
        market_override=_market(),
        product_rules_override=_product(),
        order_store=order_store,
        state_store=state_store,
    )
    assert "linked_position_id_mismatch" in report["blockers"]


def test_base_semantics_incoherent_blocks(monkeypatch, tmp_path: Path):
    report = _build(
        tmp_path,
        monkeypatch,
        position_size_base="0.03000000",
        created_at=(datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat(),
    )
    assert "base_semantics_incoherent" in report["blockers"]


def test_tool_is_read_only(monkeypatch, tmp_path: Path):
    report = _build(tmp_path, monkeypatch)
    assert report["no_state_write"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_submit"] is True
