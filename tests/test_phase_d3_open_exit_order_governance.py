from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.state_store import StateStore
from tools.show_phase_d3_open_exit_order_governance import build_report


def _seed_position(store: StateStore, *, status: str = "open") -> None:
    store.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="80000",
        position_size_base="0.06000000",
        position_size_quote="4800",
        extra={
            "bot_managed_base": "0.10000000",
            "status": status,
        },
    )


def _seed_live_exit(
    store: OrderStore,
    *,
    client_order_id: str = "phased3-BTCUSDC-TP1-pos-1",
    remaining_size: str = "0.04000000",
    created_at: str = "2026-05-26T09:49:38.767009+00:00",
) -> None:
    store.upsert_order({
        "client_order_id": client_order_id,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "exchange_order_id": "cb-order-1" if client_order_id.endswith("pos-1") else f"cb-{client_order_id}",
        "order_id": "cb-order-1" if client_order_id.endswith("pos-1") else f"cb-{client_order_id}",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.04000000",
        "remaining_size": remaining_size,
        "limit_price": "81664.97",
        "created_at": created_at,
    })


def _snapshot(status: str = "open") -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": "0",
        "filled_quote": "0",
        "remaining_size": "0.04000000",
        "fill_count": 0,
    }


def _market(best_bid: str = "81500.00", best_ask: str = "81510.00", mid: str = "81505.00") -> dict:
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid,
    }


def _product_rules() -> dict:
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
    market: dict | None = None,
    product: dict | None = None,
    position_status: str = "open",
    extra_open_order: bool = False,
    created_at: str = "2026-05-26T09:49:38.767009+00:00",
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    state_store = StateStore()
    _seed_position(state_store, status=position_status)
    _seed_live_exit(order_store, created_at=created_at)
    if extra_open_order:
        _seed_live_exit(
            order_store,
            client_order_id="phased3-BTCUSDC-TP1-pos-1-extra",
            remaining_size="0.01000000",
            created_at=created_at,
        )
    return build_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-order-1",
        linked_position_id="pos-1",
        order_store=order_store,
        state_store=state_store,
        snapshot_override=snapshot or _snapshot("open"),
        market_override=market or _market(),
        product_rules_override=product or _product_rules(),
    )


def test_open_order_near_market_recommends_keep_open(monkeypatch, tmp_path: Path):
    report = _build(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert report["coinbase_status"] == "open"
    assert report["recommendation"] == "keep_open"
    assert report["no_state_write"] is True
    assert report["blockers"] == []


def test_open_order_far_above_market_and_old_recommends_cancel_candidate(monkeypatch, tmp_path: Path):
    report = _build(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        market=_market(best_bid="78000.00", best_ask="78010.00", mid="78005.00"),
        created_at="2026-05-26T05:49:38.767009+00:00",
    )
    assert report["recommendation"] == "cancel_candidate_preview_only"
    assert report["distance_to_mid_pct"] != "0"


def test_missing_product_rules_blocks(monkeypatch, tmp_path: Path):
    report = _build(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        product={"coinbase_call_attempted": True, "coinbase_call_succeeded": False},
    )
    assert "product_rules_missing" in report["blockers"]


def test_missing_market_snapshot_blocks(monkeypatch, tmp_path: Path):
    report = _build(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        market={"coinbase_call_attempted": True, "coinbase_call_succeeded": False},
    )
    assert "market_snapshot_missing" in report["blockers"]


def test_multiple_open_d3_orders_block(monkeypatch, tmp_path: Path):
    report = _build(monkeypatch=monkeypatch, tmp_path=tmp_path, extra_open_order=True)
    assert "open_d3_order_count_not_one" in report["blockers"]


def test_local_position_closed_blocks(monkeypatch, tmp_path: Path):
    report = _build(monkeypatch=monkeypatch, tmp_path=tmp_path, position_status="closed")
    assert "local_position_not_open" in report["blockers"]


def test_available_plus_reserved_matches_bot_manageable_base(monkeypatch, tmp_path: Path):
    report = _build(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert report["available_plus_reserved_base"] == "0.10000000"
    assert report["available_reserved_matches_bot_manageable_base"] is True


def test_non_open_snapshot_recommends_reconcile_first(monkeypatch, tmp_path: Path):
    report = _build(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        snapshot={
            "coinbase_call_attempted": True,
            "coinbase_call_succeeded": True,
            "raw_status": "FILLED",
            "normalized_status": "filled",
            "filled_base": "0.04000000",
            "filled_quote": "3266.5988",
            "remaining_size": "0",
            "fill_count": 1,
        },
    )
    assert report["recommendation"] == "reconcile_first"
    assert report["coinbase_status"] == "filled"
