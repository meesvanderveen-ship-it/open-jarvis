from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_c43_lifecycle_service import build_phase_c43_lifecycle_service_report


def _cfg(tmp_path: Path, **overrides):
    base = dict(
        enable_phase_c43_lifecycle_orchestrator=True,
        phase_c43_lifecycle_allow_coinbase_poll=False,
        phase_c43_lifecycle_apply_local=False,
        phase_c43_lifecycle_build_d2_plan=False,
        phase_c43_lifecycle_persist_d2_plan=False,
        phase_c43_lifecycle_build_d3_preview=False,
        phase_c43_lifecycle_order_store_path=str(tmp_path / "orders.json"),
        phase_c43_lifecycle_order_events_path=str(tmp_path / "events.jsonl"),
        order_store_max_records=200,
        enable_phase_d2_position_executor=True,
        phase_d2_min_expected_net_edge_pct="0.0010",
        phase_d2_min_reward_to_fee_ratio="1.0",
        phase_d2_min_reward_to_risk_ratio="0.5",
        phase_d2_estimated_entry_fee_pct="0.0010",
        phase_d2_estimated_exit_fee_pct="0.0010",
        phase_d2_estimated_spread_slippage_pct="0.0010",
        phase_d2_fee_safety_buffer_pct="0.0010",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        phase_d3_max_exit_order_quote="25.00",
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_new_exit_orders_per_cycle=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _store(tmp_path: Path):
    return OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")


def _add_open_c43_order(store: OrderStore, ticker="BTC-USDC"):
    store.upsert_order({
        "client_order_id": f"phasec-{ticker.replace('-', '')}-service-test",
        "exchange_order_id": "cb-service-1",
        "order_id": "cb-service-1",
        "ticker": ticker,
        "product_id": ticker,
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "opened_via_phase_c43": True,
        "execution_action": "place_limit_buy",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "remaining_quote": "25.00",
        "remaining_size": "0.0005",
        "limit_price": "50000",
    })


def _add_open_d3_exit_order(store: OrderStore, ticker="BTC-USDC"):
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
        "exchange_order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "ticker": ticker,
        "product_id": ticker,
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00015416",
        "remaining_size": "0.00015416",
        "filled_base": "0",
        "limit_price": "71554.19",
    })


def test_service_disabled_returns_no_orchestrator_report(tmp_path: Path):
    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, enable_phase_c43_lifecycle_orchestrator=False),
        order_store=_store(tmp_path),
    )
    assert report["status"] == "disabled"
    assert report["orchestrator_report"] is None
    assert report["safety_policy"]["never_submits_to_coinbase"] is True


def test_service_default_preview_scans_all_without_coinbase_client(tmp_path: Path):
    store = _store(tmp_path)
    _add_open_c43_order(store, ticker="BTC-USDC")
    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path),
        order_store=store,
        cycle_type="full",
        source="unit_test",
    )
    assert report["status"] == "completed"
    assert report["ticker"] == "ALL"
    assert report["local_open_c43_orders_precheck"] == 1
    assert report["coinbase_client_constructed"] is False
    assert report["summary"]["coinbase_call_attempted"] is False
    assert report["summary"]["proposed_actions"] == 1
    assert report["orchestrator_report"]["proposed_actions"][0]["action"] == "no_live_snapshot"
    assert store.get_order("phasec-BTCUSDC-service-test")["status"] == "submitted"


class FakeCoinbaseClient:
    def __init__(self):
        self.calls = []

    def get_order(self, order_id):
        self.calls.append(order_id)
        return {"order": {"order_id": order_id, "product_id": "BTC-USDC", "side": "BUY", "status": "OPEN"}}

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


def test_service_coinbase_poll_requires_flag_and_open_order(tmp_path: Path):
    store = _store(tmp_path)
    client = FakeCoinbaseClient()
    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_allow_coinbase_poll=True),
        order_store=store,
        coinbase_client=client,
    )
    assert report["local_open_c43_orders_precheck"] == 0
    assert report["coinbase_client_constructed"] is False
    assert client.calls == []

    _add_open_c43_order(store, ticker="BTC-USDC")
    report2 = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_allow_coinbase_poll=True),
        order_store=store,
        coinbase_client=client,
    )
    assert report2["coinbase_client_constructed"] is True
    assert report2["summary"]["coinbase_call_attempted"] is True
    assert client.calls == ["cb-service-1"]


def test_service_uses_governance_to_block_apply_without_poll(tmp_path: Path):
    store = _store(tmp_path)
    _add_open_c43_order(store, ticker="BTC-USDC")
    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_apply_local=True),
        order_store=store,
    )
    assert report["governance_report"]["status"] == "blocked_review_required"
    assert "apply_local_requires_coinbase_poll_flag" in report["governance_report"]["blockers"]
    assert report["config"]["requested_apply_local"] is True
    assert report["config"]["effective_apply_local"] is False
    assert report["summary"]["applied_actions"] == 0
    assert store.get_order("phasec-BTCUSDC-service-test")["status"] == "submitted"


def test_service_uses_governance_poll_limit_before_constructing_client(tmp_path: Path):
    store = _store(tmp_path)
    _add_open_c43_order(store, ticker="BTC-USDC")
    _add_open_c43_order(store, ticker="ETH-USDC")
    client = FakeCoinbaseClient()
    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_allow_coinbase_poll=True, phase_c43_lifecycle_max_poll_orders_per_cycle=1),
        order_store=store,
        coinbase_client=client,
    )
    assert report["governance_report"]["status"] == "blocked_review_required"
    assert "open_c43_orders_exceed_poll_limit" in report["governance_report"]["blockers"]
    assert report["config"]["effective_allow_coinbase_poll"] is False
    assert report["coinbase_client_constructed"] is False
    assert client.calls == []


class FakeD3CoinbaseClient:
    def __init__(self):
        self.calls = []

    def get_order(self, order_id):
        self.calls.append(order_id)
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "OPEN",
                "filled_size": "0",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return []


class FakeD3FilledCoinbaseClient(FakeD3CoinbaseClient):
    def get_order(self, order_id):
        self.calls.append(order_id)
        return {
            "order": {
                "order_id": order_id,
                "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "FILLED",
                "filled_size": "0.00015416",
            }
        }

    def get_recent_fills_for_order(self, order_id, limit=100):
        return [
            {
                "order_id": order_id,
                "product_id": "BTC-USDC",
                "size": "0.00015416",
                "price": "71554.19",
                "commission": "0.01",
            }
        ]


def test_service_scans_and_polls_open_d3_exit_without_apply(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    store = _store(tmp_path)
    _add_open_d3_exit_order(store)
    client = FakeD3CoinbaseClient()

    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_allow_coinbase_poll=True),
        order_store=store,
        coinbase_client=client,
        cycle_type="heartbeat",
        source="unit_test",
    )

    d3_reports = report["d3_open_exit_lifecycle_reports"]
    assert report["local_open_c43_orders_precheck"] == 0
    assert report["local_open_d3_exit_orders_precheck"] == 1
    assert report["coinbase_client_constructed"] is True
    assert client.calls == ["81edc268-cf15-4f25-b30b-f0d5b3abb30d"]
    assert d3_reports[0]["status"] == "d3_open_exit_lifecycle_keep_open_preview"
    assert d3_reports[0]["proposed_action"] == "keep_open"
    assert d3_reports[0]["state_write_performed"] is False
    assert report["summary"]["d3_applied_actions"] == 0
    assert report["orchestrator_report"]["status"] == "skipped_no_open_c43_orders"
    assert store.get_order("phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000")["status"] == "submitted"


def test_service_empty_ticker_d3_only_does_not_call_c43_orchestrator_or_crash(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    store = _store(tmp_path)
    _add_open_d3_exit_order(store)

    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(
            tmp_path,
            phase_c43_lifecycle_allow_coinbase_poll=True,
            phase_c43_lifecycle_build_d2_plan=True,
            phase_c43_lifecycle_build_d3_preview=True,
        ),
        ticker="",
        order_store=store,
        cycle_type="heartbeat",
        source="unit_test",
    )

    assert report["status"] == "completed"
    assert report["orchestrator_report"]["status"] == "skipped_no_open_c43_orders"
    assert report["summary"]["local_d3_open_exit_orders_seen"] == 1
    assert report["summary"]["d3_applied_actions"] == 0


def test_service_filled_d3_exit_proposes_apply_without_local_apply(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    store = _store(tmp_path)
    _add_open_d3_exit_order(store)
    client = FakeD3FilledCoinbaseClient()

    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path, phase_c43_lifecycle_allow_coinbase_poll=True),
        order_store=store,
        coinbase_client=client,
        cycle_type="heartbeat",
        source="unit_test",
    )

    d3_report = report["d3_open_exit_lifecycle_reports"][0]
    assert d3_report["normalized_status"] == "filled"
    assert d3_report["proposed_action"] == "mark_filled"
    assert d3_report["state_write_performed"] is False
    assert report["summary"]["d3_applied_actions"] == 0
    assert store.get_order("phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000")["status"] == "submitted"


class FakeStateStore:
    """Minimal read-only stand-in: build_phase_c43_lifecycle_service_report's
    new D.2-retry path only ever reads positions, never writes through this."""

    def __init__(self, positions):
        self._positions = {str(k).upper(): v for k, v in positions.items()}

    def get_positions(self):
        return dict(self._positions)

    def get_position(self, ticker):
        return self._positions.get(str(ticker).upper())


def _open_position(ticker="BTC-USDC", entry_price="80.42"):
    return {
        "ticker": ticker,
        "status": "open",
        "entry_price": entry_price,
        "position_size_base": "1.0",
        "stop_price": str(float(entry_price) * 0.98),
        "take_profit_price": str(float(entry_price) * 1.02),
    }


def _retry_cfg(tmp_path: Path, **overrides):
    return _cfg(
        tmp_path,
        phase_c43_lifecycle_allow_coinbase_poll=True,
        phase_c43_lifecycle_apply_local=True,
        phase_c43_lifecycle_build_d2_plan=True,
        phase_c43_lifecycle_persist_d2_plan=False,
        **overrides,
    )


def test_service_retries_d2_for_open_position_without_ready_plan_and_no_open_order(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    state = FakeStateStore({"BTC-USDC": _open_position()})

    report = build_phase_c43_lifecycle_service_report(
        cfg=_retry_cfg(tmp_path),
        order_store=store,
        state_store=state,
        coinbase_client=FakeCoinbaseClient(),
        cycle_type="full",
        source="unit_test",
    )

    assert report["positions_needing_d2_retry"] == ["BTC-USDC"]
    assert len(report["d2_retry_orchestrator_reports"]) == 1
    assert report["governance_report"]["d2_retry_positions"]["count"] == 1
    assert report["governance_report"]["status"] == "apply_local_governed"
    retry_report = report["d2_retry_orchestrator_reports"][0]
    assert retry_report["ticker"] == "BTC-USDC"
    assert len(retry_report["d2_reports"]) == 1
    assert retry_report["d2_reports"][0]["ticker"] == "BTC-USDC"


def test_service_skips_retry_when_persisted_plan_already_ready(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state/phase_d2_position_executor_plans.json").write_text(
        '{"plans": {"BTC-USDC": {"ticker": "BTC-USDC", "status": "position_executor_plan_ready_no_live_exit_submit"}}}',
        encoding="utf-8",
    )
    store = _store(tmp_path)
    state = FakeStateStore({"BTC-USDC": _open_position()})

    report = build_phase_c43_lifecycle_service_report(
        cfg=_retry_cfg(tmp_path),
        order_store=store,
        state_store=state,
        cycle_type="full",
        source="unit_test",
    )

    assert report["positions_needing_d2_retry"] == []
    assert report["d2_retry_orchestrator_reports"] == []


def test_service_skips_retry_when_ticker_already_covered_by_open_c43_order(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    _add_open_c43_order(store, ticker="BTC-USDC")
    state = FakeStateStore({"BTC-USDC": _open_position()})

    report = build_phase_c43_lifecycle_service_report(
        cfg=_retry_cfg(tmp_path),
        order_store=store,
        state_store=state,
        coinbase_client=FakeCoinbaseClient(),
        cycle_type="full",
        source="unit_test",
    )

    assert report["positions_needing_d2_retry"] == []
    assert report["d2_retry_orchestrator_reports"] == []
    # the ticker is still handled through the normal open_c43_orders path
    assert report["local_open_c43_orders_precheck"] == 1


def test_service_retry_without_build_d2_flag_does_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = _store(tmp_path)
    state = FakeStateStore({"BTC-USDC": _open_position()})

    report = build_phase_c43_lifecycle_service_report(
        cfg=_cfg(tmp_path),  # apply_local/build_d2 both default False
        order_store=store,
        state_store=state,
        cycle_type="full",
        source="unit_test",
    )

    assert report["positions_needing_d2_retry"] == ["BTC-USDC"]
    assert report["d2_retry_orchestrator_reports"] == []
