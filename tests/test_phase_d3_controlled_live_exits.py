from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bot.atomic_io import process_lock
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d2_position_executor import build_multi_exit_bracket_lite_plan
from bot.phase_d3_controlled_live_exits import (
    D3_ACK,
    assess_phase_d3_exit_readiness,
    build_phase_d3_full_close_exit_intent,
    build_phase_d3_controlled_live_exit_report,
    build_phase_d3_exit_payload,
    build_phase_d3_risk_close_exit_intent,
    build_phase_d3_take_profit_resting_exit_intent,
    select_next_phase_d3_exit_intent,
    submit_phase_d3_controlled_exit,
)


def _cfg(monkeypatch):
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ENABLE_LIMIT_ORDER_MANAGER", "true")
    monkeypatch.setenv("ENABLE_LIVE_LIMIT_ORDERS", "true")
    monkeypatch.setenv("ENABLE_LIVE_ENTRY_ORDERS", "true")
    monkeypatch.setenv("ENABLE_LIVE_EXIT_ORDERS", "false")
    monkeypatch.setenv("ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS", "true")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "BTC-USDC,ETH-USDC")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC,ETH-USDC")
    monkeypatch.setenv("PHASE_C_MAX_ORDER_QUOTE", "100.00")
    monkeypatch.setenv("AUTONOMOUS_MAX_ORDER_QUOTE", "100.00")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE", "true")
    monkeypatch.setenv("AUTONOMOUS_ENTRY_ONLY_FIRST", "true")
    monkeypatch.setenv("AUTONOMOUS_ALLOW_EXITS", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true")
    monkeypatch.setenv("ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS", "true")
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false")
    monkeypatch.setenv("PHASE_D3_MAX_EXIT_ORDER_QUOTE", "100.00")
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")
    return BotConfig()


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "1.00",
        "bot_managed_base": "1.00",
        "position_size_quote": "100.00",
        "stop_price": "97.50",
        "invalidation_price": "97.50",
    }
    payload.update(overrides)
    return payload


def _recovered_position():
    return {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "entry_price": "77042.43",
        "position_size_base": "0.0000649067431275",
        "position_size_quote": "4.9701704868084948825",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
        "stop_price": "76000.00",
        "invalidation_price": "76000.00",
        "partial_take_profit_taken": True,
    }


def _plan(cfg):
    return build_multi_exit_bracket_lite_plan(cfg=cfg, position=_position())


def test_d3_selects_first_limit_tp_and_skips_runner(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    assert intent["label"] == "TP1"
    assert intent["side"] == "SELL"
    assert Decimal(intent["size_base"]) > Decimal("0")
    assert intent["reduce_only_local"] is True
    assert not intent["blockers"]


def test_d3_full_close_can_cover_a_110_usdc_position_without_old_buy_cap(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    cfg.phase_d3_max_exit_order_quote = Decimal("120.00")
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = _position(entry_price="100.00", position_size_base="1.00", bot_managed_base="1.00")
    intent = build_phase_d3_full_close_exit_intent(
        cfg=cfg,
        ticker="BTC-USDC",
        position=position,
        order_store=store,
        orderbook_context={"best_bid": "109.99", "best_ask": "110.00", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
        requested_base_size="1.00",
        market_evidence_price="110.00",
    )
    assert Decimal(intent["size_base"]) == Decimal("1.00")
    assert Decimal(intent["estimated_quote_value"]) == Decimal("110.01")
    assert not intent["blockers"]


def test_d3_partial_reduce_intent_is_not_exempt_from_min_quote(monkeypatch, tmp_path):
    # is_full_close=False (used for judge reduce_size, not a full close) must
    # not inherit the full-close below-minimum exemption: a too-small partial
    # sell should be blocked rather than silently allowed through.
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = _position(entry_price="100.00", position_size_base="1.00", bot_managed_base="1.00")
    intent = build_phase_d3_full_close_exit_intent(
        cfg=cfg,
        ticker="BTC-USDC",
        position=position,
        order_store=store,
        orderbook_context={"best_bid": "9.99", "best_ask": "10.00", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
        requested_base_size="0.10",
        label="PARTIAL_REDUCE",
        market_evidence_price="10.00",
        is_full_close=False,
    )
    assert "exit_quote_below_min_live_order_quote" in intent["blockers"]


def test_d3_take_profit_resting_intent_prices_at_position_take_profit_not_market(monkeypatch, tmp_path):
    # Distinct from build_phase_d3_full_close_exit_intent (prices at
    # best_ask_plus_one_tick for an immediate discretionary exit): this rests
    # a limit SELL at the position's own take_profit_price so a fast move
    # through the target fills automatically between cycles.
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = _position(
        entry_price="80.42",
        position_size_base="0.76349166",
        bot_managed_base="0.76349166",
        stop_price="80.3229",
        invalidation_price="79.98",
        take_profit_price="81.300",
    )
    intent = build_phase_d3_take_profit_resting_exit_intent(
        cfg=cfg,
        ticker="SOL-USDC",
        position=position,
        order_store=store,
        orderbook_context={"best_bid": "80.90", "best_ask": "80.95", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
    )
    assert not intent["blockers"]
    assert intent["limit_price"] == "81.30"
    assert Decimal(intent["size_base"]) == Decimal("0.76349166")
    assert intent["label"] == "TP1"
    assert intent["side"] == "SELL"


def test_d3_take_profit_resting_intent_blocked_without_take_profit_price(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = _position(
        entry_price="80.42",
        position_size_base="0.76349166",
        bot_managed_base="0.76349166",
        stop_price="80.3229",
        invalidation_price="79.98",
        take_profit_price="0",
    )
    intent = build_phase_d3_take_profit_resting_exit_intent(
        cfg=cfg,
        ticker="SOL-USDC",
        position=position,
        order_store=store,
        orderbook_context={"best_bid": "80.90", "best_ask": "80.95", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
    )
    assert "take_profit_price_missing_for_resting_tp_exit" in intent["blockers"]


def test_d3_take_profit_resting_intent_blocks_duplicate_label(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    position = _position(
        order_id="pos-1",
        entry_price="80.42",
        position_size_base="0.76349166",
        bot_managed_base="0.76349166",
        stop_price="80.3229",
        invalidation_price="79.98",
        take_profit_price="81.300",
    )
    store.upsert_order({
        "client_order_id": "phased3-SOLUSDC-TP1-pos-1-existing",
        "exchange_order_id": "exchange-phased3-SOLUSDC-TP1-pos-1-existing",
        "ticker": "SOL-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.76349166",
        "remaining_size": "0.76349166",
        "limit_price": "81.30",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })
    intent = build_phase_d3_take_profit_resting_exit_intent(
        cfg=cfg,
        ticker="SOL-USDC",
        position=position,
        order_store=store,
        orderbook_context={"best_bid": "80.90", "best_ask": "80.95", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
    )
    assert "duplicate_exit_label_already_open_for_position" in intent["blockers"]


def test_d3_risk_close_is_blocked_from_post_only_maker_limit_route(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")

    intent = build_phase_d3_risk_close_exit_intent(
        cfg=cfg,
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        orderbook_context={"best_bid": "97.49", "best_ask": "97.50", "freshness_status": "fresh"},
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
        requested_base_size="1.00",
        market_evidence_price="97.50",
    )

    assert intent["label"] == "RISK_CLOSE"
    assert "risk_close_requires_controlled_stop_exit_route" in intent["blockers"]
    assert intent["risk_close_semantics"]["maker_limit_route_allowed"] is False
    assert build_phase_d3_exit_payload(cfg=cfg, exit_intent=intent)["accepted"] is False


def test_d3_ignores_trailing_stop_intent_as_live_tp(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    plan["exits"] = [{"label": "RUNNER", "base_size": "1", "limit_price": "105", "fraction": "1", "trailing_stop": True}]
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    assert intent["label"] == "NONE"
    assert "no_limit_tp_exit_intent_available_for_d3" in intent["blockers"]
    assert any("runner_or_trailing_exit_preview_only" in warning for warning in intent["warnings"])


def test_d3_blocks_blind_exit_when_position_risk_state_incomplete(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    pos = _position(stop_price="0", invalidation_price="0")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=pos, order_store=store)
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=pos, plan=plan, exit_intent=intent, order_store=store)
    assert "position_risk_incomplete_stop_or_invalidation_missing" in intent["blockers"]
    assert "position_risk_incomplete_stop_or_invalidation_missing" in readiness["blockers"]


def test_d3_blocks_without_live_exit_flags(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=_position(), plan=plan, exit_intent=intent, order_store=store, submit_live=True, human_ack=D3_ACK)
    assert readiness["ready"] is False
    assert "live_exit_orders_disabled" in readiness["blockers"]
    assert "autonomous_allow_exits_disabled" in readiness["blockers"]
    assert "phase_c_disable_exit_limit_orders_still_true" in readiness["blockers"]


def test_d3_preview_ready_no_submit_when_submit_live_false(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=_position(), plan=plan, exit_intent=intent, order_store=store, submit_live=False)
    assert readiness["ready"] is True
    assert readiness["submit_armed"] is False
    assert "submit_live_argument_false_preview_only" in readiness["passed_checks"]


def test_d3_payload_is_sell_limit_gtc(monkeypatch):
    cfg = _cfg(monkeypatch)
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position())
    payload = build_phase_d3_exit_payload(cfg=cfg, exit_intent=intent)
    assert payload["accepted"] is True
    preview = payload["coinbase_payload_preview"]
    assert preview["side"] == "SELL"
    assert "limit_limit_gtc" in preview["order_configuration"]


def test_d3_live_context_quantizes_limit_price_before_payload(monkeypatch):
    cfg = _cfg(monkeypatch)
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(
        cfg=cfg,
        plan=plan,
        position=_position(),
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
    )
    payload = build_phase_d3_exit_payload(cfg=cfg, exit_intent=intent)
    assert Decimal(intent["raw_limit_price"]) >= Decimal(intent["limit_price"])
    assert intent["price_increment_used"] == "0.01"
    assert payload["price_precision_context"] == "exchange_rules_price_increment"


def test_d3_no_oversell_with_existing_reservation(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "exchange_order_id": "exchange-phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "1.00",
        "remaining_size": "1.00",
        "limit_price": "103.75",
    })
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    assert "no_available_base_after_existing_exit_reservations" in intent["blockers"]
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=_position(), plan=plan, exit_intent=intent, order_store=store)
    assert "sell_base_missing_or_zero" in readiness["blockers"] or "sell_base_exceeds_available_unreserved_base" in readiness["blockers"]


def test_d3_submit_live_calls_client_only_when_all_armed(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    cfg.enable_live_exit_orders = True
    cfg.autonomous_allow_exits = True
    cfg.phase_c_disable_exit_limit_orders = False
    cfg.enable_phase_d3_actual_exit_submit = True
    cfg.autonomous_entry_only_first = False
    cfg.phase_d3_runtime_submit_ack = D3_ACK
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)

    class Client:
        def __init__(self):
            self.calls = []
        def place_limit_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"order_id": "cb-exit-1", "success": True}

    client = Client()
    lock_path = tmp_path / "runtime_mutation.lock"
    monkeypatch.setenv("RUN_TRADER_LOOP_LOCK_PATH", str(lock_path))
    with process_lock(lock_path):
        result = submit_phase_d3_controlled_exit(
            cfg=cfg,
            position=_position(),
            plan=plan,
            exit_intent=intent,
            order_store=store,
            coinbase_client=client,
            submit_live=True,
            human_ack=D3_ACK,
            audit_path=tmp_path / "audit.jsonl",
        )
    assert result["live_order_submitted"] is True
    assert client.calls and client.calls[0]["side"] == "SELL"
    assert store.open_exit_orders("BTC-USDC")
    assert result["mutation_lock"] == {"acquired": True, "reentrant": True}


def test_d3_constant_argument_cannot_arm_submit_without_runtime_ack(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    cfg.enable_live_exit_orders = True
    cfg.autonomous_allow_exits = True
    cfg.phase_c_disable_exit_limit_orders = False
    cfg.enable_phase_d3_actual_exit_submit = True
    cfg.autonomous_entry_only_first = False
    cfg.phase_d3_runtime_submit_ack = ""
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)

    class Client:
        calls = 0

        def place_limit_order(self, **kwargs):
            self.calls += 1
            raise AssertionError("runtime ACK gap must block before Coinbase")

    client = Client()
    result = submit_phase_d3_controlled_exit(
        cfg=cfg,
        position=_position(),
        plan=plan,
        exit_intent=intent,
        order_store=store,
        coinbase_client=client,
        submit_live=True,
        human_ack=D3_ACK,
        audit_path=tmp_path / "audit.jsonl",
    )

    assert result["live_submission_attempted"] is False
    assert "phase_d3_runtime_submit_ack_missing_or_invalid" in result["readiness"]["blockers"]
    assert client.calls == 0


def test_d3_submit_success_false_is_rejected_not_open(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    cfg.enable_live_exit_orders = True
    cfg.autonomous_allow_exits = True
    cfg.phase_c_disable_exit_limit_orders = False
    cfg.enable_phase_d3_actual_exit_submit = True
    cfg.autonomous_entry_only_first = False
    cfg.phase_d3_runtime_submit_ack = D3_ACK
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(
        cfg=cfg,
        plan=plan,
        position=_position(),
        order_store=store,
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1"},
    )

    class Client:
        def __init__(self):
            self.calls = []
        def place_limit_order(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "success": False,
                "error_response": {
                    "error": "INVALID_PRICE_PRECISION",
                    "message": "Too many decimals in order price",
                    "preview_failure_reason": "PREVIEW_INVALID_PRICE_PRECISION",
                },
            }

    client = Client()
    result = submit_phase_d3_controlled_exit(
        cfg=cfg,
        position=_position(),
        plan=plan,
        exit_intent=intent,
        order_store=store,
        coinbase_client=client,
        submit_live=True,
        human_ack=D3_ACK,
        audit_path=tmp_path / "audit.jsonl",
    )
    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["status"] == "d3_controlled_exit_submit_rejected"
    assert result["reject_reason"] == "INVALID_PRICE_PRECISION"
    assert result["live_exit_policy"]["execution_status"] == "d3_controlled_live_exit_submit_attempted"
    rejected = store.get_order(intent["client_order_id"])
    assert rejected is not None
    assert rejected["status"] == "rejected"
    assert rejected["remaining_size"] == "0"
    assert rejected["exchange_order_id"] == ""
    assert rejected["closed_at"]
    assert store.open_exit_orders("BTC-USDC") == []


def test_d3_rejected_record_does_not_trigger_duplicate_exit_blockers(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-rejected",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "rejected",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.10",
        "remaining_size": "0",
        "limit_price": "103.75",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=_position(), plan=plan, exit_intent=intent, order_store=store)
    assert "duplicate_exit_label_already_open_for_position" not in intent["blockers"]
    assert "duplicate_open_exit_order_for_position_action" not in readiness["blockers"]
    assert store.open_exit_orders("BTC-USDC") == []


def test_d3_report_uses_fresh_d2_preview_and_does_not_submit(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = build_phase_d3_controlled_live_exit_report(cfg=cfg, ticker="BTC-USDC", position=_position(), order_store=store, submit_live=False, audit_path=tmp_path / "audit.jsonl")
    assert report["status"] == "d3_controlled_exit_ready_no_submit"
    assert report["live_order_submitted"] is False
    assert report["selected_exit_intent"]["label"] == "TP1"
    assert "reservation_governance" in report
    assert report["reservation_governance"]["reserved_base_open_exit_orders"] == "0"
    assert report["reservation_governance"]["available_base_after_reservations"] == "1.00"
    assert report["reservation_governance"]["min_size_ready"] is True


def test_d3_report_includes_reservation_governance_when_no_position(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = build_phase_d3_controlled_live_exit_report(cfg=cfg, ticker="BTC-USDC", order_store=store, submit_live=False, audit_path=tmp_path / "audit.jsonl")
    assert report["status"] == "d3_no_manageable_open_position"
    assert "reservation_governance" in report
    assert report["reservation_governance"]["position_present"] is False
    assert report["reservation_governance"]["future_controlled_sell_pilot_coherent"] is False


def test_d3_report_includes_reservation_governance_when_plan_missing(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    bad_plan = {"ticker": "BTC-USDC", "status": "position_executor_plan_blocked"}
    report = build_phase_d3_controlled_live_exit_report(
        cfg=cfg,
        ticker="BTC-USDC",
        position=_position(),
        plan=bad_plan,
        order_store=store,
        submit_live=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    assert report["status"] == "d3_no_ready_position_executor_plan"
    assert "reservation_governance" in report
    assert report["reservation_governance"]["future_controlled_sell_pilot_coherent"] is False


def test_d3_report_reservation_governance_reflects_existing_open_exit_orders(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "exchange_order_id": "exchange-phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.25",
        "remaining_size": "0.25",
        "limit_price": "103.75",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })
    report = build_phase_d3_controlled_live_exit_report(
        cfg=cfg,
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        submit_live=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    rg = report["reservation_governance"]
    assert rg["reserved_base_open_exit_orders"] == "0.25"
    assert rg["available_base_after_reservations"] == "0.75"
    assert rg["future_controlled_sell_pilot_coherent"] is True


def test_d3_report_matches_existing_open_exit_via_recovery_lineage(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        "order_id": "bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "limit_price": "81664.97",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })
    plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=_recovered_position())
    report = build_phase_d3_controlled_live_exit_report(
        cfg=cfg,
        ticker="BTC-USDC",
        position=_recovered_position(),
        plan=plan,
        order_store=store,
        submit_live=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    rg = report["reservation_governance"]
    assert rg["position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"
    assert rg["open_exit_orders_count"] == 1
    assert rg["reserved_base_open_exit_orders"] == "0.00006489"
    assert report["selected_exit_intent"]["position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"
    assert report["selected_exit_intent"]["position_id"] == "76310097-849e-481c-b587-ba44bc3330fe"


def test_d3_report_read_only_integration_does_not_submit(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    report = build_phase_d3_controlled_live_exit_report(
        cfg=cfg,
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        submit_live=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    assert report["live_submission_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["submit_result"]["live_submission_attempted"] is False
    assert report["submit_result"]["live_order_submitted"] is False


def test_d3_submit_still_works_when_central_gate_flags_and_ack_are_green(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    cfg.enable_live_exit_orders = True
    cfg.autonomous_allow_exits = True
    cfg.phase_c_disable_exit_limit_orders = False
    cfg.enable_phase_d3_actual_exit_submit = True
    cfg.autonomous_entry_only_first = False
    cfg.phase_d3_runtime_submit_ack = D3_ACK
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)

    class Client:
        def __init__(self):
            self.calls = []
        def place_limit_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"order_id": "cb-exit-1", "success": True}

    client = Client()
    result = submit_phase_d3_controlled_exit(
        cfg=cfg,
        position=_position(),
        plan=plan,
        exit_intent=intent,
        order_store=store,
        coinbase_client=client,
        submit_live=True,
        human_ack=D3_ACK,
        audit_path=tmp_path / "audit.jsonl",
    )
    assert result["live_order_submitted"] is True
    assert len(client.calls) == 1


def test_d3_blocks_duplicate_exit_label_for_same_position(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "exchange_order_id": "exchange-phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.10",
        "remaining_size": "0.10",
        "limit_price": "103.75",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })
    plan = _plan(cfg)
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=_position(), order_store=store)
    assert "duplicate_exit_label_already_open_for_position" in intent["blockers"]
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=_position(), plan=plan, exit_intent=intent, order_store=store)
    assert "duplicate_open_exit_order_for_position_action" in readiness["blockers"] or "duplicate_exit_label_already_open_for_position" in readiness["blockers"]


def test_d3_blocks_partial_sell_under_min_live_quote(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    small_position = {
        **_position(),
        "position_size_base": "0.25",
        "bot_managed_base": "0.25",
        "position_size_quote": "25.00",
    }
    plan = {
        "ticker": "BTC-USDC",
        "status": "position_executor_plan_ready",
        "position_id": "pos-1",
        "exits": [
            {
                "label": "TP1",
                "base_size": "0.10",
                "limit_price": "103.75",
                "estimated_quote": "10.375",
                "execution_action": "place_limit_sell",
            }
        ],
    }
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=small_position, order_store=store)
    assert "exit_quote_below_min_live_order_quote" in intent["blockers"]


def test_d3_allows_full_close_under_min_live_quote(monkeypatch, tmp_path):
    cfg = _cfg(monkeypatch)
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    small_position = {
        **_position(),
        "position_size_base": "0.10",
        "bot_managed_base": "0.10",
        "position_size_quote": "10.00",
    }
    plan = {
        "ticker": "BTC-USDC",
        "status": "position_executor_plan_ready",
        "position_id": "pos-1",
        "exits": [
            {
                "label": "TP_CLOSE",
                "base_size": "0.10",
                "limit_price": "103.75",
                "estimated_quote": "10.375",
                "execution_action": "place_limit_sell_close",
            }
        ],
    }
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=small_position, order_store=store)
    assert "exit_quote_below_min_live_order_quote" not in intent["blockers"]
    assert "full_close_below_min_live_order_quote_allowed" in intent["warnings"]
