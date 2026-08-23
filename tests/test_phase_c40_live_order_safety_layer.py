from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from bot.phase_c40_live_order_safety_layer import (
    assess_c40_order_safety,
    build_phase_c40_live_order_safety_report,
    collect_live_open_orders_snapshot,
    normalize_live_order,
)


def cfg(actual=False, exits=False):
    return SimpleNamespace(
        enable_phase_c_actual_coinbase_submit=actual,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=exits,
    )


def live_order(**overrides):
    data = {
        "client_order_id": "phasec-BTCUSDC-test-123",
        "order_id": "cb-order-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "OPEN",
        "base_size": "0.0001",
        "quote_size": "10.00",
        "limit_price": "100000",
            }
    data.update(overrides)
    return data


def local_order(**overrides):
    data = {
        "client_order_id": "phasec-BTCUSDC-test-123",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "size_quote": "10.00",
        "limit_price": "100000",
        "created_at": "2026-05-15T13:00:00+00:00",
    }
    data.update(overrides)
    return data


def test_c40_default_no_snapshot_does_not_call_coinbase(tmp_path):
    report = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        order_store_path=tmp_path / "open_orders.json",
        order_events_path=tmp_path / "order_events.jsonl",
    )
    assert report["status"] == "live_order_safety_clear_no_live_orders"
    assert report["coinbase_poll"]["coinbase_call_attempted"] is False
    assert report["dry_run_cancel_plan"]["cancel_attempted_by_this_tool"] is False
    assert report["safety_policy"]["default_does_not_call_coinbase"] is True


def test_c40_matches_known_pilot_order(tmp_path):
    # Write local store shape used by OrderStore.
    p = tmp_path / "open_orders.json"
    p.write_text('{"orders":{"phasec-BTCUSDC-test-123":{"client_order_id":"phasec-BTCUSDC-test-123","ticker":"BTC-USDC","side":"BUY","status":"submitted","size_quote":"10.00","limit_price":"100000"}}}', encoding="utf-8")
    report = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        live_orders_snapshot=[live_order()],
        order_store_path=p,
        order_events_path=tmp_path / "events.jsonl",
    )
    assert report["status"] == "live_order_safety_clear_known_orders"
    counts = report["safety_assessment"]["counts"]
    assert counts["live_open_orders"] == 1
    assert counts["live_unmanaged_orders"] == 0
    assert report["dry_run_cancel_plan"]["cancel_submitted"] is False


def test_c40_detects_unmanaged_live_order(tmp_path):
    report = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        live_orders_snapshot=[live_order(client_order_id="manual-web-order-1")],
        order_store_path=tmp_path / "open_orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert report["status"] == "live_order_safety_blocked"
    assert "unmanaged_live_open_orders_detected" in report["safety_assessment"]["blockers"]
    assert report["safety_assessment"]["counts"]["live_unmanaged_orders"] == 1
    assert report["dry_run_cancel_plan"]["cancel_attempted_by_this_tool"] is False


def test_c40_expired_and_partial_fill_recommendation():
    now = datetime(2026, 5, 15, 14, 0, tzinfo=timezone.utc)
    order = normalize_live_order(live_order(status="OPEN", filled_size="0.00005", expires_at="2026-05-15T13:30:00+00:00"))
    safety = assess_c40_order_safety(cfg=cfg(), live_orders=[order], local_orders=[order], now=now)
    assert safety["counts"]["partial_fill_like_orders"] == 1
    reasons = safety["recommendations"][0]["reasons"]
    assert "order_expired_but_still_open" in reasons
    assert "partial_fill_detected_prepare_reconciliation" in reasons


class FakeClient:
    def __init__(self):
        self.called = False

    def list_orders(self, **kwargs):
        self.called = True
        return {"orders": [live_order()]}


def test_c40_coinbase_poll_requires_explicit_allow_and_client(tmp_path):
    client = FakeClient()
    report = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        coinbase_client=client,
        allow_coinbase_poll=False,
        order_store_path=tmp_path / "open_orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert client.called is False
    assert report["coinbase_poll"]["coinbase_call_attempted"] is False

    report2 = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        coinbase_client=client,
        allow_coinbase_poll=True,
        order_store_path=tmp_path / "open_orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert client.called is True
    assert report2["coinbase_poll"]["coinbase_call_attempted"] is True


def test_c40_live_exits_forbidden_blocker():
    safety = assess_c40_order_safety(cfg=cfg(exits=True), live_orders=[], local_orders=[])
    assert "live_exit_orders_enabled_forbidden_in_c40" in safety["blockers"]
