from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d2_position_executor import is_d2_manageable_open_position
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report
from bot.state_store import StateStore
from bot.strategy_engine import StrategyEngine


def _engine(tmp_path: Path) -> StrategyEngine:
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.state = StateStore()
    engine.order_store = OrderStore(
        path=str(tmp_path / "state" / "open_orders.json"),
        log_path=str(tmp_path / "logs" / "order_events.jsonl"),
        max_orders=50,
    )
    engine.cfg = SimpleNamespace()
    engine.position_epsilon_base = Decimal("0.00000001")
    engine.min_trade_quote_usdc = Decimal("10")
    engine._to_decimal = StrategyEngine._to_decimal
    engine._now_iso = lambda: "2026-05-26T01:05:00+00:00"
    engine._apply_current_inventory_policy_to_payload = lambda payload: None
    return engine


def _live_action_engine(tmp_path: Path) -> StrategyEngine:
    engine = _engine(tmp_path)
    engine.cfg.execution_mode = "live"
    engine._write_jsonl = lambda *args, **kwargs: None
    engine._get_live_available_base = lambda ticker: Decimal("0.0001297967431275")
    engine._extract_position_inventory_state = StrategyEngine._extract_position_inventory_state.__get__(engine, StrategyEngine)
    return engine


def test_phase_c43_pilot_tiny_residual_stays_open_for_governance_review(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.00012979",
        position_size_quote="9.9993369897",
        entry_reason="phase-c43-pilot",
        extra={
            "status": "open",
            "bot_managed_base": "0.00012979",
            "opened_via_phase_c43_live_order": True,
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_created_from_fill_status": "filled",
        },
    )

    result = engine._sync_local_position_to_live_balance(
        ticker="BTC-USDC",
        position=engine.state.get_position("BTC-USDC"),
        live_available_base=Decimal("0.00012979"),
        current_price=Decimal("76700"),
        note="inventory_sync",
    )

    assert result["status"] == "open"
    assert Decimal(str(result["position_size_base"])) > Decimal("0")
    assert Decimal(str(result["bot_managed_base"])) > Decimal("0")
    assert result["tiny_residual_close_skipped_for_phase_c43_pilot_review"] is True
    assert (
        result["tiny_residual_close_skip_reason"]
        == "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review"
    )
    assert result["last_heartbeat_status"] == "open_tiny_phase_c43_governance_review"
    assert is_d2_manageable_open_position(result, ticker="BTC-USDC") is True


def test_old_unmanaged_tiny_residual_still_closes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="legacy-1",
        entry_price="77042.43",
        position_size_base="0.00012979",
        position_size_quote="9.9993369897",
        entry_reason="legacy",
        extra={
            "status": "open",
            "bot_managed_base": "0.00012979",
        },
    )

    result = engine._sync_local_position_to_live_balance(
        ticker="BTC-USDC",
        position=engine.state.get_position("BTC-USDC"),
        live_available_base=Decimal("0.00012979"),
        current_price=Decimal("76700"),
        note="inventory_sync",
    )

    assert result["status"] == "closed"
    assert result["position_size_base"] == "0"
    assert result["bot_managed_base"] == "0"
    assert result["synthetic_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert result["last_heartbeat_status"] == "closed_tiny_residual"


def test_inventory_sync_exchange_positions_keeps_recovered_phase_c43_pilot_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg.allowed_tickers = ["BTC-USDC"]

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {"currency": "BTC", "available_balance": {"value": "0.0001297967431275"}},
                ]
            }

        def get_public_ticker(self, ticker):
            assert ticker == "BTC-USDC"
            return {"best_bid": "76667.46", "best_ask": "76667.47"}

    engine.client = FakeClient()

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "opened_via_phase_c43_live_order": True,
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_created_from_fill_status": "filled",
            "recovered_from_synthetic_tiny_residual_close": True,
            "recovery_reason": "phase_c43_pilot_position_restored_for_d2_d3_governance_review",
            "recovered_at": "2026-05-26T01:34:44.561626+00:00",
            "synced_from_exchange": True,
            "setup_type": "inventory_sync",
            "tiny_residual_close_skipped_for_phase_c43_pilot_review": True,
            "tiny_residual_close_skip_reason": "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review",
        },
    )

    result = engine._sync_exchange_inventory_positions()
    position = engine.state.get_position("BTC-USDC")

    assert result["synced"] == ["BTC-USDC"]
    assert result["closed"] == []
    assert position["status"] == "open"
    assert Decimal(str(position["position_size_base"])) > Decimal("0")
    assert Decimal(str(position["bot_managed_base"])) > Decimal("0")
    assert position["last_heartbeat_status"] == "open_tiny_phase_c43_governance_review"
    assert position["tiny_residual_close_skipped_for_phase_c43_pilot_review"] is True
    assert is_d2_manageable_open_position(position, ticker="BTC-USDC") is True

    d3_report = build_phase_d3_controlled_live_exit_report(
        ticker="BTC-USDC",
        cfg=engine.cfg,
        state_store=engine.state,
        order_store=engine.order_store,
        coinbase_client=None,
    )
    assert d3_report["status"] == "d3_controlled_exit_ready_no_submit"
    assert d3_report["live_submission_attempted"] is False
    assert d3_report["live_order_submitted"] is False


def test_inventory_sync_keeps_position_open_when_matching_open_d3_exit_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg.allowed_tickers = ["BTC-USDC"]

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {"currency": "BTC", "available_balance": {"value": "0.0000649067431275"}},
                ]
            }

        def get_public_ticker(self, ticker):
            assert ticker == "BTC-USDC"
            return {"best_bid": "76586.06", "best_ask": "76586.07"}

    engine.client = FakeClient()

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "opened_via_phase_c43_live_order": True,
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_created_from_fill_status": "filled",
            "synced_from_exchange": True,
            "entry_reason": "inventory_sync",
        },
    )
    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-live",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "cb-live-open-1",
        "order_id": "cb-live-open-1",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "limit_price": "81664.97",
    })

    result = engine._sync_exchange_inventory_positions()
    position = engine.state.get_position("BTC-USDC")

    assert result["closed"] == []
    assert position["status"] == "open"
    assert Decimal(str(position["position_size_base"])) > Decimal("0")
    assert Decimal(str(position["bot_managed_base"])) > Decimal("0")
    assert (
        position["tiny_residual_close_skip_reason"]
        == "inventory_sync_position_kept_open_due_to_open_d3_exit_order"
    )
    assert "inventory_sync_position_kept_open_due_to_open_d3_exit_order" in str(position["notes"])


def test_open_d3_exit_for_other_position_does_not_protect_inventory_sync_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg.allowed_tickers = ["BTC-USDC"]

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {"currency": "BTC", "available_balance": {"value": "0.0000649067431275"}},
                ]
            }

        def get_public_ticker(self, ticker):
            return {"best_bid": "76586.06", "best_ask": "76586.07"}

    engine.client = FakeClient()
    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "opened_via_phase_c43_live_order": False,
            "phase_c43_client_order_id": "",
            "phase_c43_exchange_order_id": "",
            "position_created_from_fill_status": "",
            "synced_from_exchange": True,
            "entry_reason": "inventory_sync",
            "close_reason": "",
            "synthetic_close_reason": "",
        },
    )
    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-other",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "other-pos",
        "exchange_order_id": "cb-other",
        "order_id": "cb-other",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
    })

    result = engine._sync_exchange_inventory_positions()
    position = engine.state.get_position("BTC-USDC")
    assert result["closed"] == ["BTC-USDC"]
    assert position["status"] == "closed"
    assert position["last_heartbeat_status"] == "closed_tiny_residual"


def test_open_d3_exit_missing_exchange_order_id_still_protects_inventory_sync_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg.allowed_tickers = ["BTC-USDC"]

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {"currency": "BTC", "available_balance": {"value": "0.0000649067431275"}},
                ]
            }

        def get_public_ticker(self, ticker):
            return {"best_bid": "76586.06", "best_ask": "76586.07"}

    engine.client = FakeClient()
    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "opened_via_phase_c43_live_order": False,
            "phase_c43_client_order_id": "",
            "phase_c43_exchange_order_id": "",
            "position_created_from_fill_status": "",
            "synced_from_exchange": True,
            "entry_reason": "inventory_sync",
        },
    )
    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-no-exchange",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "",
        "order_id": "",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
    })

    result = engine._sync_exchange_inventory_positions()
    position = engine.state.get_position("BTC-USDC")
    assert result["closed"] == []
    assert position["status"] == "open"
    assert position["last_position_close_guard_reason"] == "open_d3_exit_reservation_prevents_position_close"


def test_open_d3_exit_with_recovered_linked_position_prevents_inventory_sync_close(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _engine(tmp_path)
    engine.cfg.allowed_tickers = ["BTC-USDC"]

    class FakeClient:
        def get_accounts(self):
            return {
                "accounts": [
                    {"currency": "BTC", "available_balance": {"value": "0.0000649067431275"}},
                ]
            }

        def get_public_ticker(self, ticker):
            return {"best_bid": "76586.06", "best_ask": "76586.07"}

    engine.client = FakeClient()
    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="77042.43",
        position_size_base="0.0000649067431275",
        position_size_quote="4.9701704868084948825",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "synced_from_exchange": True,
            "entry_reason": "inventory_sync",
        },
    )
    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        "order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "limit_price": "81664.97",
    })

    result = engine._sync_exchange_inventory_positions()
    position = engine.state.get_position("BTC-USDC")
    assert result["closed"] == []
    assert position["status"] == "open"
    assert position["tiny_residual_close_skip_reason"] == "inventory_sync_position_kept_open_due_to_open_d3_exit_order"
    assert Decimal(str(position["position_size_base"])) > Decimal("0")
    assert Decimal(str(position["bot_managed_base"])) > Decimal("0")


def test_position_action_close_keeps_phase_c43_tiny_residual_open_for_governance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _live_action_engine(tmp_path)

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="76310097-849e-481c-b587-ba44bc3330fe",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="phase_c43_live_limit_buy_filled",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
            "opened_via_phase_c43_live_order": True,
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "position_created_from_fill_status": "filled",
        },
    )
    position = engine.state.get_position("BTC-USDC")

    result = engine._handle_position_action(
        "BTC-USDC",
        position,
        {
            "action": "close",
            "side": "SELL",
            "size_base": "0.0001297967431275",
            "reason": "governance_close_test",
            "metadata": {
                "current_price": "76824.82",
                "updated_position": position,
                "inventory_plan": {
                    "sell_total_base": "0.0001297967431275",
                    "sell_bot_base": "0.0001297967431275",
                    "sell_legacy_base": "0",
                    "sell_scope": "bot_only",
                },
            },
        },
        {"market": {"mid_price": "76824.82"}},
    )

    restored = engine.state.get_position("BTC-USDC")
    assert result["status"] == "position_action_close_skipped_for_phase_c43_tiny_residual_governance"
    assert result["executed"] is False
    assert Decimal(str(restored["position_size_base"])) > Decimal("0")
    assert Decimal(str(restored["bot_managed_base"])) > Decimal("0")
    assert restored["status"] == "open"
    assert restored["last_heartbeat_status"] == "open_tiny_phase_c43_governance_review"
    assert (
        restored["tiny_residual_close_skip_reason"]
        == "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review"
    )
    assert "position_action_close_skipped_for_phase_c43_tiny_residual_governance" in str(restored["notes"])


def test_position_action_close_still_closes_non_phase_c43_dust_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    engine = _live_action_engine(tmp_path)

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="legacy-close-1",
        entry_price="77042.43",
        position_size_base="0.0001297967431275",
        position_size_quote="9.9555030025505861625",
        entry_reason="legacy",
        extra={
            "status": "open",
            "bot_managed_base": "0.0001297967431275",
        },
    )
    position = engine.state.get_position("BTC-USDC")

    result = engine._handle_position_action(
        "BTC-USDC",
        position,
        {
            "action": "close",
            "side": "SELL",
            "size_base": "0.0001297967431275",
            "reason": "legacy_close_test",
            "metadata": {
                "current_price": "76824.82",
                "updated_position": position,
                "inventory_plan": {
                    "sell_total_base": "0.0001297967431275",
                    "sell_bot_base": "0.0001297967431275",
                    "sell_legacy_base": "0",
                    "sell_scope": "bot_only",
                },
            },
        },
        {"market": {"mid_price": "76824.82"}},
    )

    closed = engine.state.get_position("BTC-USDC")
    assert result["status"] == "position_closed_locally_dust_below_min_notional"
    assert closed["status"] == "closed"
    assert closed["position_size_base"] == "0"
    assert closed["bot_managed_base"] == "0"
