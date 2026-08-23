from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_c43_controlled_entry_pilot import (
    ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
    build_controlled_entry_pilot_report,
)
from bot.phase_c43_one_entry_smoke_test import C43_ONE_ENTRY_SMOKE_ACK
from bot.phase_d31_lifecycle_readiness import D31_ENTRY_ARM_ACK
from bot.state_store import StateStore


def cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_d3_actual_exit_submit=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c_allowed_tickers=["BTC-USDC", "SUI-USDC"],
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
        phase_d3_max_open_exit_orders=4,
        enable_phase_c43_lifecycle_orchestrator=True,
        phase_c43_lifecycle_allow_coinbase_poll=False,
        phase_c43_lifecycle_apply_local=False,
        phase_c43_lifecycle_build_d2_plan=False,
        phase_c43_lifecycle_persist_d2_plan=False,
        phase_c43_lifecycle_build_d3_preview=False,
        phase_c43_lifecycle_max_poll_orders_per_cycle=4,
        phase_c43_lifecycle_max_apply_actions_per_cycle=4,
        phase_c43_lifecycle_apply_requires_coinbase_poll=True,
        phase_c43_lifecycle_block_apply_when_live_exits_enabled=True,
        # D3.2 health config used by readiness report
        enable_deepseek_preprocess=False,
        enable_anthropic_fallback=False,
        llm_context_hygiene_enabled=True,
        llm_payload_string_max_chars=60000,
        llm_repeated_fragment_max_repeats=3,
        openai_model="gpt-5.4-mini",
        openai_analyst_model="gpt-5.4-mini",
        openai_judge_model="gpt-5.5",
        phase_d32_block_on_recent_llm_corrupt=True,
        phase_d32_block_on_recent_provider_errors=True,
        phase_d32_llm_health_window_minutes=240,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeCoinbaseClient:
    def __init__(self):
        self.orders = []

    def place_limit_order(self, ticker, side, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({
            "ticker": ticker,
            "side": side,
            "base_size": str(base_size),
            "limit_price": str(limit_price),
            "client_order_id": client_order_id,
            "post_only": post_only,
        })
        return {"success": True, "success_response": {"order_id": "cb-controlled-1", "client_order_id": client_order_id}}


def _stores(tmp_path: Path):
    return (
        OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl"),
        StateStore(),
    )


def test_preview_can_simulate_actual_submit_without_order(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=False,
        order_store=order_store,
        state_store=state_store,
        simulate_actual_submit_for_preview=True,
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_preview_ready"
    assert report["preview_actual_submit_simulated"] is True
    assert report["live_order_submitted"] is False
    assert report["counts_after"]["total_open_live_entry_orders"] == 0
    assert report["orchestrator_preview_after"]["coinbase_call_attempted"] is False
    assert report["one_shot_actual_entry_submit_armed_process_local"] is False
    assert report["one_shot_actual_entry_submit_env_mutation"] is False


def test_live_submit_requires_both_acks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack="wrong",
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "d31_human_ack_missing_or_wrong" in report["blockers"]
    assert client.orders == []
    assert report["counts_after"]["total_open_live_entry_orders"] == 0


def test_one_shot_arming_allows_d31_readiness_without_env_mutation(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()
    original_cfg = cfg(enable_phase_c_actual_coinbase_submit=False)

    report = build_controlled_entry_pilot_report(
        cfg=original_cfg,
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_live_order_submitted"
    assert report["one_shot_actual_entry_submit_armed_process_local"] is True
    assert report["one_shot_actual_entry_submit_env_mutation"] is False
    assert report["d31_readiness"]["entry_readiness"]["config_flags"]["enable_phase_c_actual_coinbase_submit"] is True
    assert original_cfg.enable_phase_c_actual_coinbase_submit is False
    assert len(client.orders) == 1


def test_one_shot_arming_does_not_mutate_original_cfg(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()
    original_cfg = cfg(enable_phase_c_actual_coinbase_submit=False)

    report = build_controlled_entry_pilot_report(
        cfg=original_cfg,
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert original_cfg.enable_phase_c_actual_coinbase_submit is False
    assert "phase_c_actual_coinbase_submit_enabled" in report["smoke_report"]["preflight"]["passed_checks"]


def test_one_shot_arming_requires_exact_new_ack(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack="wrong",
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "one_shot_arm_ack_missing_or_wrong" in report["one_shot_actual_entry_submit_blockers"]
    assert report["one_shot_actual_entry_submit_armed_process_local"] is False
    assert client.orders == []


def test_one_shot_arming_requires_existing_c43_and_d31_acks(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack="wrong",
        d31_human_ack="wrong",
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "c43_human_ack_missing_or_wrong" in report["blockers"]
    assert "d31_human_ack_missing_or_wrong" in report["blockers"]
    assert client.orders == []


def test_one_shot_arming_blocks_non_btc_ticker(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="SUI-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("1.23"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.01", "quote_increment": "0.0001", "base_min_size": "0.01", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "one_shot_actual_entry_submit_ticker_not_btc_usdc" in report["one_shot_actual_entry_submit_blockers"]
    assert client.orders == []


def test_one_shot_arming_blocks_quote_above_10(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.01"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "one_shot_actual_entry_submit_quote_above_10_or_missing" in report["one_shot_actual_entry_submit_blockers"]
    assert client.orders == []


def test_one_shot_arming_blocks_when_open_c43_order_exists(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    order_store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-existing-one-shot",
        "exchange_order_id": "cb-existing-one-shot",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "execution_action": "place_limit_buy",
        "opened_via_phase_c43": True,
        "remaining_quote": "10.00",
    })
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "one_shot_actual_entry_submit_requires_zero_open_c43_orders" in report["one_shot_actual_entry_submit_blockers"]
    assert client.orders == []


def test_one_shot_arming_blocks_when_sell_flags_not_safe(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False, enable_live_exit_orders=True),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "one_shot_actual_entry_submit_requires_live_exit_orders_false" in report["one_shot_actual_entry_submit_blockers"]
    assert client.orders == []


def test_one_shot_arming_logs_process_local_scope(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        one_shot_actual_entry_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=FakeCoinbaseClient(),
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["one_shot_actual_entry_submit_scope"] == "single_runner_process_only"
    assert report["one_shot_actual_entry_submit_env_mutation"] is False
    assert report["ack_tokens"]["one_shot_arm_ack_required"] == ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK


def test_preview_mode_does_not_require_one_shot_arm(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=False,
        one_shot_actual_entry_submit=False,
        one_shot_arm_ack="",
        order_store=order_store,
        state_store=state_store,
        simulate_actual_submit_for_preview=True,
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_preview_ready"
    assert report["one_shot_actual_entry_submit_armed_process_local"] is False
    assert report["one_shot_actual_entry_submit_blockers"] == []


def test_live_submit_places_exactly_one_order_and_keeps_lifecycle_preview(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_live_order_submitted"
    assert report["live_order_submitted"] is True
    assert len(client.orders) == 1
    assert client.orders[0]["post_only"] is True
    assert report["counts_before"]["total_open_live_entry_orders"] == 0
    assert report["counts_after"]["total_open_live_entry_orders"] == 1
    assert report["governance_after"]["effective_flags"]["allow_coinbase_poll"] is False
    assert report["orchestrator_preview_after"]["coinbase_call_attempted"] is False
    assert report["orchestrator_preview_after"]["d3_previews"] == []


def test_existing_open_order_blocks_one_entry_pilot(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    # Create one existing open C.4.3-like order.
    order_store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-existing",
        "exchange_order_id": "cb-existing",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "execution_action": "place_limit_buy",
        "opened_via_phase_c43": True,
        "remaining_quote": "10.00",
    })
    client = FakeCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("75000"),
        submit_live=True,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["status"] == "controlled_entry_blocked"
    assert "existing_open_c43_orders_block_one_entry_pilot" in report["blockers"]
    assert client.orders == []

class FakeRejectCoinbaseClient:
    def __init__(self):
        self.orders = []

    def place_limit_order(self, ticker, side, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({
            "ticker": ticker,
            "side": side,
            "base_size": str(base_size),
            "limit_price": str(limit_price),
            "client_order_id": client_order_id,
            "post_only": post_only,
        })
        return {
            "success": False,
            "error_response": {
                "error": "INVALID_LIMIT_PRICE_POST_ONLY",
                "message": "Invalid limit price for post-only order",
                "preview_failure_reason": "PREVIEW_INVALID_LIMIT_PRICE_POST_ONLY",
            },
        }


def test_live_submit_reject_does_not_leave_open_order(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    order_store, state_store = _stores(tmp_path)
    client = FakeRejectCoinbaseClient()

    report = build_controlled_entry_pilot_report(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("103240"),
        submit_live=True,
        c43_human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        d31_human_ack=D31_ENTRY_ARM_ACK,
        coinbase_client=client,
        order_store=order_store,
        state_store=state_store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )

    assert report["live_submission_attempted"] is True
    assert report["live_order_submitted"] is False
    assert report["status"] == "controlled_entry_submit_requested_no_order_submitted"
    assert report["smoke_report"]["c43_result"]["submit_result"]["status"] == "phase_c_live_order_rejected_by_coinbase"
    assert report["smoke_report"]["c43_result"]["local_order_record"]["status"] == "submit_rejected"
    assert report["counts_after"]["total_open_live_entry_orders"] == 0
    assert report["governance_after"]["local_open_c43_orders"]["count"] == 0
    assert order_store.open_entry_orders("BTC-USDC") == []
    assert order_store.final_orders("BTC-USDC")[0]["status"] == "submit_rejected"
