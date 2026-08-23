from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_open_exit_position_guard import (
    build_open_d3_exit_position_guard_report,
    match_open_d3_exit_order_to_position,
    should_block_position_close_due_to_open_d3_exit,
)
from bot.phase_d3_local_position_recovery import (
    PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
    build_phase_d3_local_position_recovery_report,
)
from bot.state_store import StateStore
from bot.strategy_engine import StrategyEngine


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


def _seed_position(
    state: StateStore,
    *,
    status: str = "open",
    position_size_base: str = "0.0000649067431275",
    reserved: str = "0.00006489",
    bot_managed: str = "0.0001297967431275",
    extra: dict | None = None,
) -> None:
    payload = {
        "ticker": "BTC-USDC",
        "status": status,
        "order_id": "pos-1",
        "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "position_size_base": position_size_base,
        "position_size_quote": "0",
        "bot_managed_base": bot_managed,
        "reserved_base_open_exit_orders": reserved,
        "monitoring_enabled": True,
    }
    if extra:
        payload.update(extra)
    state.upsert_position("BTC-USDC", payload)


def _seed_open_exit(
    orders: OrderStore,
    *,
    status: str = "submitted",
    remaining_size: str = "0.00006489",
    client_order_id: str = "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
    exchange_order_id: str = "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
    linked_position_id: str = "76310097-849e-481c-b587-ba44bc3330fe",
    extra: dict | None = None,
) -> None:
    payload = {
        "client_order_id": client_order_id,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": status,
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": linked_position_id,
        "exchange_order_id": exchange_order_id,
        "order_id": exchange_order_id,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": remaining_size,
        "remaining_size": remaining_size,
        "filled_base": "0",
        "fill_count": 0,
        "limit_price": "81664.97",
    }
    if extra:
        payload.update(extra)
    orders.upsert_order(payload)


def _engine(tmp_path: Path) -> StrategyEngine:
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.state = StateStore()
    engine.order_store = OrderStore(
        path=str(tmp_path / "state" / "open_orders.json"),
        log_path=str(tmp_path / "logs" / "order_events.jsonl"),
        max_orders=50,
    )
    engine.position_epsilon_base = Decimal("0.00000001")
    engine.min_trade_quote_usdc = Decimal("10")
    engine._to_decimal = StrategyEngine._to_decimal
    engine._normalize_ticker = StrategyEngine._normalize_ticker
    engine._now_iso = lambda: "2026-05-26T18:10:00+00:00"
    engine._apply_current_inventory_policy_to_payload = lambda payload: None
    engine._closed_position_has_unmanaged_legacy_inventory = lambda *args, **kwargs: False
    engine._should_skip_tiny_residual_close_for_phase_c43_pilot_review = StrategyEngine._should_skip_tiny_residual_close_for_phase_c43_pilot_review.__get__(engine, StrategyEngine)
    engine._tiny_residual_keep_open_reason = StrategyEngine._tiny_residual_keep_open_reason.__get__(engine, StrategyEngine)
    engine._matching_open_d3_live_exit_order_for_position = StrategyEngine._matching_open_d3_live_exit_order_for_position.__get__(engine, StrategyEngine)
    engine._keep_phase_c43_pilot_position_open_for_governance_review = StrategyEngine._keep_phase_c43_pilot_position_open_for_governance_review.__get__(engine, StrategyEngine)
    engine._sync_local_position_to_live_balance = StrategyEngine._sync_local_position_to_live_balance.__get__(engine, StrategyEngine)
    engine._sync_exchange_inventory_positions = StrategyEngine._sync_exchange_inventory_positions.__get__(engine, StrategyEngine)
    return engine


def test_guard_blocks_close_when_open_d3_exit_exists(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["status"] = "closed"

    report = build_open_d3_exit_position_guard_report(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
        order_store=orders,
    )

    assert report["should_block_close"] is True
    assert report["guard_status"] == "guard_blocked_open_d3_exit_reservation"
    assert report["matching_open_d3_exit_count"] == 1
    assert report["guard_version"] == "v2"


def test_guard_blocks_zeroing_position_size_base_when_open_d3_exit_exists(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["position_size_base"] = "0"

    assert should_block_position_close_due_to_open_d3_exit(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
        order_store=orders,
    ) is True


def test_guard_blocks_zeroing_bot_managed_base_when_open_d3_exit_exists(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["bot_managed_base"] = "0"

    assert should_block_position_close_due_to_open_d3_exit(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
        order_store=orders,
    ) is True


def test_guard_allows_close_without_open_d3_exit(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    _seed_position(state)
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["status"] = "closed"

    assert should_block_position_close_due_to_open_d3_exit(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
    ) is False


def test_guard_allows_close_for_final_d3_order_or_controlled_lifecycle_apply(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["status"] = "closed"
    proposed["position_size_base"] = "0"
    proposed["bot_managed_base"] = "0"

    assert should_block_position_close_due_to_open_d3_exit(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
        order_store=orders,
        caller_reason="controlled_d3_lifecycle_apply",
        evidence_status="filled",
    ) is False


def test_guard_v2_matches_via_recovery_linked_position_id(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        extra={
            "order_id": "",
            "phase_c43_exchange_order_id": "",
            "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        },
    )
    _seed_open_exit(orders)
    match = match_open_d3_exit_order_to_position(
        orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000") or {},
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        order_store=orders,
    )

    assert match["matched"] is True
    assert match["match_strategy"] == "linked_position_id"


def test_guard_v2_matches_via_phase_c43_exchange_order_id(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        extra={
            "order_id": "",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "recovery_linked_position_id": "",
        },
    )
    _seed_open_exit(orders)

    match = match_open_d3_exit_order_to_position(
        orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000") or {},
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        order_store=orders,
    )

    assert match["matched"] is True
    assert match["match_strategy"] == "linked_position_id"


def test_guard_v2_matches_via_replacement_references(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        extra={
            "order_id": "",
            "phase_c43_exchange_order_id": "",
            "recovery_linked_position_id": "",
            "source_order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
            "source_client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        },
    )
    _seed_open_exit(
        orders,
        linked_position_id="",
        extra={
            "replacement_of_client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
            "replacement_of_exchange_order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        },
    )

    match = match_open_d3_exit_order_to_position(
        orders.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000") or {},
        ticker="BTC-USDC",
        position=state.get_position("BTC-USDC"),
        order_store=orders,
    )

    assert match["matched"] is True
    assert "replacement_of_client_order_id" in match["match_strategy"]
    assert "replacement_of_exchange_order_id" in match["match_strategy"]


def test_guard_v2_matches_via_single_open_sell_ticker_fallback(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        extra={
            "order_id": "",
            "phase_c43_exchange_order_id": "",
            "recovery_linked_position_id": "",
        },
    )
    _seed_open_exit(
        orders,
        linked_position_id="",
        exchange_order_id="",
        extra={"order_id": "", "client_order_id": "ticker-fallback-open-order"},
    )
    current = state.get_position("BTC-USDC")
    proposed = dict(current)
    proposed["status"] = "closed"

    report = build_open_d3_exit_position_guard_report(
        ticker="BTC-USDC",
        current_position=current,
        proposed_position=proposed,
        order_store=orders,
    )

    assert report["should_block_close"] is True
    assert report["last_guard_match_strategy"] == "ticker_single_open_sell_fallback"


def test_state_store_blocks_tiny_residual_close_and_keeps_position_open(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)

    updated = state.mark_position_closed_tiny_residual(
        "BTC-USDC",
        close_reason="inventory_sync_live_notional_below_min_trade_quote",
        close_price="76000",
        residual_base="0.0000649067431275",
        residual_quote="4.92",
    )

    assert updated["status"] == "open"
    assert updated["position_size_base"] == "0.0000649067431275"
    assert updated["bot_managed_base"] == "0.0001297967431275"
    assert updated["reserved_base_open_exit_orders"] == "0.00006489"
    assert updated["last_position_close_guard_reason"] == "open_d3_exit_reservation_prevents_position_close"
    assert updated["last_guard_version"] == "v2"
    assert updated["last_guard_match_strategy"] == "linked_position_id"
    assert updated["last_guard_matching_order_ids"] == [
        "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
    ]
    assert updated["last_guard_checked_at"]


def test_guard_blocks_tiny_residual_close_without_exchange_order_id(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(
        orders,
        exchange_order_id="",
        extra={"order_id": ""},
    )

    updated = state.mark_position_closed_tiny_residual(
        "BTC-USDC",
        close_reason="inventory_sync_live_notional_below_min_trade_quote",
        close_price="76000",
        residual_base="0.0000649067431275",
        residual_quote="4.92",
    )

    assert updated["status"] == "open"
    assert updated["last_guard_version"] == "v2"


def test_inventory_tiny_residual_route_keeps_position_open_with_open_d3_exit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)

    _seed_position(engine.state)
    _seed_open_exit(engine.order_store)

    result = engine._sync_local_position_to_live_balance(
        ticker="BTC-USDC",
        position=engine.state.get_position("BTC-USDC"),
        live_available_base=Decimal("0.0000649067431275"),
        current_price=Decimal("75816.735"),
        note="inventory_sync_live_notional_below_min_trade_quote",
    )

    assert result["status"] == "open"
    assert result["position_size_base"] == "0.0000649067431275"
    assert result["bot_managed_base"] == "0.0001297967431275"
    assert result["reserved_base_open_exit_orders"] == "0.00006489"


def test_inventory_sync_closed_list_stays_empty_when_guard_blocks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg = type("Cfg", (), {"allowed_tickers": ["BTC-USDC"]})()

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {
                        "currency": "BTC",
                        "available_balance": {"value": "0.0000649067431275"},
                    }
                ]
            }

        def get_public_ticker(self, _ticker):
            return {"best_bid": "75713.27", "best_ask": "75713.28"}

    engine.client = FakeClient()
    _seed_position(engine.state, extra={"synced_from_exchange": True, "entry_reason": "inventory_sync"})
    _seed_open_exit(engine.order_store)

    report = engine._sync_exchange_inventory_positions()

    assert report["closed"] == []
    assert report["synced"] == ["BTC-USDC"]
    assert engine.state.get_position("BTC-USDC")["status"] == "open"


def test_strategy_or_position_close_route_is_blocked_by_state_store_guard(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)

    updated = state.mark_position_closed(
        "BTC-USDC",
        close_reason="position_closed_locally_dust_below_min_notional",
        close_price="75816.735",
    )

    assert updated["status"] == "open"
    assert updated["position_size_base"] == "0.0000649067431275"
    assert updated["bot_managed_base"] == "0.0001297967431275"


def test_recovery_tooling_remains_allowed(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "closed",
            "order_id": "pos-1",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_size_base": "0",
            "position_size_quote": "0",
            "bot_managed_base": "0",
            "reserved_base_open_exit_orders": "0.00006489",
            "close_reason": "inventory_sync_live_notional_below_min_trade_quote",
        },
    )
    _seed_open_exit(orders)

    report = build_phase_d3_local_position_recovery_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        position_size_base="0.0000649067431275",
        reserved_base_open_exit_orders="0.00006489",
        bot_managed_base="0.0001297967431275",
        apply=True,
        recovery_ack=PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "d3_local_position_recovery_applied"
    assert state.get_position("BTC-USDC")["status"] == "open"


def test_cancel_replace_pilot_preflight_no_longer_sees_drift_after_guard_block(tmp_path: Path, monkeypatch) -> None:
    from bot.phase_d3_cancel_replace_pilot_preflight import build_phase_d3_cancel_replace_pilot_preflight_report

    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_open_exit(orders)
    state.mark_position_closed_tiny_residual(
        "BTC-USDC",
        close_reason="inventory_sync_live_notional_below_min_trade_quote",
        close_price="75816.735",
        residual_base="0.0000649067431275",
        residual_quote="4.92",
    )

    report = build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        exchange_order_id="bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "cancel_replace_pilot_preflight_needs_fresh_open_evidence"
    assert report["local_position_status"] == "open"
