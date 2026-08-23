from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bot.coinbase_order_snapshot import normalize_coinbase_order_snapshot
from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import (
    _C43_LIFECYCLE_APPLY_AUTHORITY,
    reconcile_phase_c43_fills_to_positions,
)
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY, build_multi_exit_bracket_lite_plan
from tools.show_function_preservation_audit import build_audit_report


class FakeStateStore:
    def __init__(self):
        self.positions = {}

    def get_position(self, ticker):
        return self.positions.get(str(ticker).upper())

    def get_positions(self):
        return dict(self.positions)

    def create_position(self, *, ticker, side, order_id, entry_price, position_size_base, position_size_quote, entry_reason="", extra=None):
        pos = {
            "ticker": str(ticker).upper(),
            "status": "open",
            "last_side": side,
            "order_id": order_id,
            "entry_price": entry_price,
            "position_size_base": position_size_base,
            "position_size_quote": position_size_quote,
            "bot_managed_base": position_size_base,
            "entry_reason": entry_reason,
            "stop_price": "49000",
        }
        if extra:
            pos.update(extra)
        self.positions[str(ticker).upper()] = pos
        return pos


def _cfg():
    return SimpleNamespace(
        phase_d2_min_expected_net_edge_pct="0.0125",
        phase_d2_min_reward_to_fee_ratio="3.0",
        phase_d2_min_reward_to_risk_ratio="1.5",
        phase_d2_estimated_entry_fee_pct="0.0040",
        phase_d2_estimated_exit_fee_pct="0.0040",
        phase_d2_estimated_spread_slippage_pct="0.0020",
        phase_d2_fee_safety_buffer_pct="0.0025",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
    )


def test_coinbase_snapshot_falls_back_to_raw_order_filled_value():
    snap = normalize_coinbase_order_snapshot(
        {
            "order_id": "cb-1",
            "client_order_id": "phasec-BTCUSDC-fill",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0001309",
            "filled_value": "9.999724581",
            "average_filled_price": "76392.09",
        }
    )
    assert snap["normalized_status"] == "filled"
    assert snap["filled_quote"] == "9.999724581"


def test_c43_reconcile_sets_position_created_and_uses_nested_quote(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order(
        {
            "client_order_id": "phasec-BTCUSDC-fill",
            "exchange_order_id": "cb-1",
            "order_id": "cb-1",
            "ticker": "BTC-USDC",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "submitted",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "opened_via_phase_c43": True,
            "execution_action": "place_limit_buy",
            "size_quote": "10.00",
            "size_base": "0.00013090",
            "remaining_quote": "10.00",
            "remaining_size": "0.00013090",
            "limit_price": "76392.09",
        }
    )
    state = FakeStateStore()
    nested = {
        "client_order_id": "phasec-BTCUSDC-fill",
        "exchange_order_id": "cb-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "raw_status": "FILLED",
        "normalized_status": "filled",
        "filled_base": "0.0001309",
        "filled_quote": "0",
        "avg_fill_price": "76392.09",
        "raw_order": {"filled_value": "9.999724581", "number_of_fills": "2"},
    }
    report = reconcile_phase_c43_fills_to_positions(
        cfg=_cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[nested],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert report["actions"][0]["action"] == "filled_to_position"
    order = store.get_order("phasec-BTCUSDC-fill")
    assert order["status"] == "filled"
    assert order["position_created"] is True
    assert order["position_link_source"] == "fill_to_position"
    assert order["position_created_from_fill_status"] == "filled"
    assert order["filled_quote_value"] == "9.999724581"
    assert state.get_position("BTC-USDC")["position_size_quote"] == "9.999724581"


def test_audit_accepts_filled_c43_when_position_links_by_phase_ids(tmp_path: Path):
    root = tmp_path
    (root / "state").mkdir()
    (root / "logs").mkdir()
    (root / ".env").write_text(
        "\n".join(
            [
                "REPLICATION_ENABLED=false",
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
                "ENABLE_LIVE_EXIT_ORDERS=false",
                "AUTONOMOUS_ALLOW_EXITS=false",
                "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false",
                "ENABLE_LIVE_LIMIT_ORDERS=true",
                "ENABLE_LIVE_ENTRY_ORDERS=true",
                "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
            ]
        )
        + "\n"
    )
    (root / "state/open_orders.json").write_text(
        json.dumps(
            {
                "orders": {
                    "phasec-BTCUSDC-fill": {
                        "client_order_id": "phasec-BTCUSDC-fill",
                        "exchange_order_id": "cb-1",
                        "order_id": "cb-1",
                        "ticker": "BTC-USDC",
                        "side": "BUY",
                        "status": "filled",
                        "mode": "live",
                        "source_mode": "autonomous_small_live",
                        "opened_via_phase_c43": True,
                        "execution_action": "place_limit_buy",
                    }
                }
            }
        )
    )
    (root / "state/positions.json").write_text(
        json.dumps(
            {
                "BTC-USDC": {
                    "ticker": "BTC-USDC",
                    "status": "open",
                    "order_id": "cb-1",
                    "phase_c43_client_order_id": "phasec-BTCUSDC-fill",
                    "phase_c43_exchange_order_id": "cb-1",
                    "position_size_base": "0.0001309",
                    "entry_price": "76392.09",
                }
            }
        )
    )
    report = build_audit_report(root, window_minutes=240)
    warnings = report["order_store"]["warnings"]
    assert not any("filled_c43_without_position_created" in w for w in warnings)


def test_d2_default_tp2_is_above_tp1_when_tp1_requirement_is_high():
    cfg = _cfg()
    plan = build_multi_exit_bracket_lite_plan(
        cfg=cfg,
        position={
            "ticker": "BTC-USDC",
            "status": "open",
            "order_id": "pos-1",
            "entry_price": "76392.09",
            "position_size_base": "0.001",
            "position_size_quote": "76.39209",
            "bot_managed_base": "0.001",
            "stop_price": "74100.3273",
            "invalidation_price": "74100.3273",
        },
    )
    assert plan["status"] == D2_PLAN_STATUS_READY
    tp1 = next(x for x in plan["exits"] if x["label"] == "TP1")
    tp2 = next(x for x in plan["exits"] if x["label"] == "TP2")
    assert float(tp2["limit_price"]) > float(tp1["limit_price"])


def test_d2_accepts_c45_position_with_quote_and_entry_price_only():
    from bot.phase_d2_position_executor import build_phase_d2_position_executor_report

    class Store:
        def __init__(self, pos):
            self.pos = pos
        def get_position(self, ticker):
            return self.pos
        def get_positions(self):
            return {self.pos["ticker"]: self.pos}

    pos = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "cb-1",
        "phase_c43_client_order_id": "phasec-BTCUSDC-fill",
        "phase_c43_exchange_order_id": "cb-1",
        "entry_price": "76392.09",
        "position_size_quote": "9.999724581",
        "stop_price": "74100.3273",
        "invalidation_price": "74100.3273",
    }
    report = build_phase_d2_position_executor_report(cfg=_cfg(), ticker="BTC-USDC", state_store=Store(pos))
    assert report["status"] == D2_PLAN_STATUS_READY
    assert report["selected_position_present"] is True
    assert report["open_position_count"] == 1
    assert "ghost_or_zero_base_selected_position_ignored" not in report.get("warnings", [])
    assert float(report["plan"]["entry"]["base_size"]) > 0


def test_d2_accepts_c45_position_with_filled_base_fields():
    from bot.phase_d2_position_executor import build_phase_d2_position_executor_report

    class Store:
        def __init__(self, pos):
            self.pos = pos
        def get_position(self, ticker):
            return self.pos
        def get_positions(self):
            return {self.pos["ticker"]: self.pos}

    pos = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "cb-2",
        "entry_price": "76392.09",
        "filled_size": "0.0001309",
        "filled_quote_value": "9.999724581",
        "stop_price": "74100.3273",
        "invalidation_price": "74100.3273",
    }
    report = build_phase_d2_position_executor_report(cfg=_cfg(), ticker="BTC-USDC", state_store=Store(pos))
    assert report["status"] == D2_PLAN_STATUS_READY
    assert report["selected_position_present"] is True
    assert report["plan"]["entry"]["base_size"] == "0.0001309"


def test_d2_report_exposes_persistence_and_linkage_fields(tmp_path: Path):
    from bot.phase_d2_position_executor import build_phase_d2_position_executor_report

    class Store:
        def __init__(self, pos):
            self.pos = pos
        def get_position(self, ticker):
            return self.pos
        def get_positions(self):
            return {self.pos["ticker"]: self.pos}

    pos = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "cb-3",
        "phase_c43_client_order_id": "phasec-BTCUSDC-fill",
        "source_order_id": "cb-3",
        "entry_price": "76392.09",
        "position_size_base": "0.0001309",
        "position_size_quote": "9.999724581",
        "stop_price": "74100.3273",
        "invalidation_price": "74100.3273",
    }
    plans_path = tmp_path / "plans.json"
    report = build_phase_d2_position_executor_report(cfg=_cfg(), ticker="BTC-USDC", state_store=Store(pos), persist_plan=True, plans_path=plans_path, audit_path=tmp_path / "audit.jsonl")
    assert report["persisted"] is True
    assert report["persisted_path"] == str(plans_path)
    assert report["persisted_ticker_key"] == "BTC-USDC"
    assert report["linked_position_id"] == "cb-3"
    assert report["source_order_id"] == "cb-3"
    assert report["source_client_order_id"] == "phasec-BTCUSDC-fill"
