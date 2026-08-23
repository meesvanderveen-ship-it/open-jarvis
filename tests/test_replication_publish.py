from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from requests import exceptions as requests_exceptions

from bot.order_store import OrderStore
import bot.phase_c43_autonomous_entry_live as c43
import bot.phase_d3_controlled_live_exits as d3
from bot.phase_d2_position_executor import build_multi_exit_bracket_lite_plan
from replication.config import ReplicationConfig
from replication.lifecycle_publisher import (
    LIFECYCLE_ENDPOINT,
    LifecyclePublishConfig,
    LifecycleReplicaPublisher,
    build_lifecycle_order_event,
)
from replication.models import ReplicationEnvelope
from replication.publisher import ReplicaPublisher


class FakeResponse:
    def __init__(self, *, ok: bool = True, status_code: int = 200, payload: dict | None = None):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload or {"accepted": True}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | None = None, exc: Exception | None = None):
        self.response = response or FakeResponse()
        self.exc = exc
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exc:
            raise self.exc
        return self.response


def _replication_config(enabled: bool = True) -> ReplicationConfig:
    return ReplicationConfig(
        enabled=enabled,
        replica_url="https://replica.example.invalid",
        shared_hmac_secret="fixture-secret",
        source_bot_name="SERVER1-MASTER",
        timeout_seconds=5,
        verify_tls=True,
    )


def test_replication_disabled_skips_without_http(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    publisher = ReplicaPublisher(config=_replication_config(enabled=False))
    fake = FakeSession()
    publisher.session = fake

    result = publisher.publish(
        ReplicationEnvelope(
            event_id="evt-disabled",
            timestamp="2026-06-13T00:00:00+00:00",
            source_bot="SERVER1-MASTER",
            ticker="BTC-USDC",
            decision="approve_trade",
            side="BUY",
        )
    )

    assert result["skipped"] is True
    assert result["reason"] == "replication_disabled"
    assert fake.calls == []


def test_decision_publisher_hmac_signs_exact_raw_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    publisher = ReplicaPublisher(config=_replication_config(enabled=True))
    fake = FakeSession()
    publisher.session = fake
    envelope = ReplicationEnvelope(
        event_id="evt-decision",
        timestamp="2026-06-13T00:00:00+00:00",
        source_bot="SERVER1-MASTER",
        ticker="BTC-USDC",
        decision="approve_trade",
        side="BUY",
    )

    result = publisher.publish(envelope)

    assert result["ok"] is True
    call = fake.calls[0]
    raw = call["data"]
    expected = hmac.new(b"fixture-secret", raw, hashlib.sha256).hexdigest()
    assert call["url"] == "https://replica.example.invalid/api/replica/decision"
    assert call["headers"]["x-replica-signature"] == expected
    assert json.loads(raw.decode("utf-8"))["event_id"] == "evt-decision"


def _lifecycle_config(*, enabled: bool = True, lifecycle: bool = True, http: bool = True) -> LifecyclePublishConfig:
    return LifecyclePublishConfig(
        replication_config=_replication_config(enabled=enabled),
        lifecycle_enabled=lifecycle,
        allow_http_transport=http,
    )


def _lifecycle_event(event_type: str = "c4_entry_order") -> dict:
    return build_lifecycle_order_event(
        event_type=event_type,
        ticker="BTC-USDC",
        event_id=f"evt-{event_type}",
        order={
            "product_id": "BTC-USDC",
            "side": "SELL" if event_type == "d3_live_exit_intent" else "BUY",
            "client_order_id": "client-1",
            "exchange_order_id": "exchange-1",
            "limit_price": "100.00",
            "quote_size": "10.00",
            "base_size": "0.10",
            "linked_position_id": "pos-1",
            "phase": "D3" if event_type == "d3_live_exit_intent" else "C4.3",
        },
    )


def test_lifecycle_publisher_hmac_and_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    publisher = LifecycleReplicaPublisher(config=_lifecycle_config())
    fake = FakeSession()
    publisher.session = fake

    result = publisher.publish_lifecycle_best_effort(_lifecycle_event())

    assert result["ok"] is True
    call = fake.calls[0]
    raw = call["data"]
    expected = hmac.new(b"fixture-secret", raw, hashlib.sha256).hexdigest()
    assert call["url"] == "https://replica.example.invalid" + LIFECYCLE_ENDPOINT
    assert call["headers"]["x-replica-signature"] == expected
    assert json.loads(raw.decode("utf-8"))["event_type"] == "c4_entry_order"


def test_lifecycle_publisher_catches_timeout_and_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    publisher = LifecycleReplicaPublisher(config=_lifecycle_config())
    publisher.session = FakeSession(exc=requests_exceptions.ReadTimeout("slow follower"))

    result = publisher.publish_lifecycle_best_effort(_lifecycle_event())

    assert result["ok"] is False
    assert result["skipped"] is True
    assert result["reason"] == "lifecycle_replication_unavailable"
    assert result["error_category"] == "read_timeout"
    assert result["http_attempted"] is True


def _c43_cfg():
    return SimpleNamespace(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote="25.00",
        phase_c_max_open_entry_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_disable_exit_limit_orders=True,
        phase_c_live_order_post_only=True,
        autonomous_max_order_quote="25.00",
        autonomous_max_open_orders=4,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=True,
        autonomous_allow_exits=False,
        order_store_max_records=200,
    )


def test_c43_successful_submit_emits_c4_entry_order(tmp_path: Path, monkeypatch) -> None:
    emitted = []
    monkeypatch.setattr(c43, "publish_lifecycle_event_best_effort", lambda event: emitted.append(event) or {"ok": True})
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")

    class Client:
        def place_limit_order(self, **kwargs):
            return {"success": True, "order_id": "cb-buy-1", "client_order_id": kwargs.get("client_order_id")}

    result = c43.build_phase_c43_guard_and_submit_preparation(
        cfg=_c43_cfg(),
        ticker="BTC-USDC",
        analysis={
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "25.00", "valid_trade_plan": True},
            "trade_plan": {
                "valid_trade_plan": True,
                "plan_action": "prepare_resting_limit_entry",
                "entry_zone_low": "49999",
                "entry_zone_high": "50000",
                "preferred_limit_price": "50000",
                    "invalidation_price": "49000",
                    "stop_loss_price": "49000",
                    "take_profit_1": "51000",
                    "take_profit_2": "52000",
                    "do_not_chase_above": "50100",
                    "setup_type": "reclaim_retest",
                    "max_quote_size": "25.00",
                },
                "feature_pack": {
                    "market": {"mid_price": "50000", "best_bid": "49999", "best_ask": "50001", "spread_pct": "0.00004"},
                    "orderbook_context": {"snapshot_available": True, "freshness_status": "fresh", "best_bid": "49999", "best_ask": "50001"},
                "product_rules": {"price_increment": "0.01", "base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
                "decision_context": {
                    "pending_order_intent": {
                        "status": "needs_fresh_analysis",
                        "trigger_ready": True,
                        "requires_fresh_judge_and_risk": True,
                    }
                }
            },
        },
        execution_plan={
            "execution_action": "place_limit_buy",
            "plan_action": "prepare_resting_limit_entry",
                "prepare_resting_limit_entry": True,
                "read_only": True,
                "expiry_hours": 6,
            "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.01"},
        },
        order_intent={
            "ticker": "BTC-USDC",
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "plan_action": "prepare_resting_limit_entry",
            "prepare_resting_limit_entry": True,
            "trigger_ready": True,
            "size_quote": "25.00",
            "limit_price": "50000",
            "intent_id": "intent-1",
            "product_rules": {"price_increment": "0.01", "base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        },
        coinbase_client=Client(),
        order_store=store,
        submit_live=True,
        product_rules={"price_increment": "0.01", "base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
    )

    assert result["live_order_submitted"] is True
    assert emitted[0]["event_type"] == "c4_entry_order"
    assert emitted[0]["order"]["exchange_order_id"] == "cb-buy-1"


def _d3_cfg():
    cfg = _c43_cfg()
    cfg.enable_live_exit_orders = True
    cfg.autonomous_allow_exits = True
    cfg.phase_c_disable_exit_limit_orders = False
    cfg.enable_phase_d3_actual_exit_submit = True
    cfg.enable_phase_d3_controlled_live_exits = True
    cfg.autonomous_entry_only_first = False
    cfg.phase_d3_runtime_submit_ack = d3.D3_ACK
    cfg.phase_d3_exit_order_post_only = True
    cfg.phase_d3_max_exit_order_quote = "25.00"
    cfg.phase_d3_max_open_exit_orders = 4
    cfg.phase_d3_max_new_exit_orders_per_cycle = 1
    return cfg


def test_d3_successful_submit_emits_live_exit_intent(tmp_path: Path, monkeypatch) -> None:
    emitted = []
    monkeypatch.setattr(d3, "publish_lifecycle_event_best_effort", lambda event: emitted.append(event) or {"ok": True})
    cfg = _d3_cfg()
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "0.25",
        "bot_managed_base": "0.25",
        "position_size_quote": "25.00",
        "stop_price": "97.50",
        "invalidation_price": "97.50",
    }
    plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=position)
    intent = d3.select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, order_store=store)

    class Client:
        def place_limit_order(self, **kwargs):
            return {"success": True, "order_id": "cb-sell-1"}

    result = d3.submit_phase_d3_controlled_exit(
        cfg=cfg,
        position=position,
        plan=plan,
        exit_intent=intent,
        order_store=store,
        coinbase_client=Client(),
        submit_live=True,
        human_ack=d3.D3_ACK,
        audit_path=tmp_path / "audit.jsonl",
    )

    assert result["live_order_submitted"] is True
    assert emitted[0]["event_type"] == "d3_live_exit_intent"
    assert emitted[0]["order"]["exchange_order_id"] == "cb-sell-1"
    assert emitted[0]["order"]["linked_position_id"] == "pos-1"
