from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d3_controlled_exit_pilot import (
    D3_CANDIDATE_FINGERPRINT_VERSION,
    ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
    build_d3_candidate_fingerprint,
    build_controlled_exit_pilot_report,
)
from bot.phase_d3_controlled_live_exits import D3_ACK
from bot.state_store import StateStore


def _cfg(monkeypatch, **overrides):
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
    monkeypatch.setenv("AUTONOMOUS_ALLOW_EXITS", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true")
    monkeypatch.setenv("ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS", "true")
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false")
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    cfg = BotConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _position():
    return {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-live-1",
        "entry_price": "77042.43",
        "position_size_base": "0.00012979",
        "bot_managed_base": "0.00012979",
        "position_size_quote": "9.9993369897",
        "stop_price": "74731.1571",
    }


def _plan(label: str = "TP1"):
    return {
        "ticker": "BTC-USDC",
        "status": "position_executor_plan_ready_no_live_exit_submit",
        "plan_id": "d2-BTC-USDC-fixed",
        "plan_fingerprint": "fp-1",
        "plan_fingerprint_schema_version": "d2_plan_fingerprint_v1",
        "position_id": "pos-live-1",
        "exits": [
            {"label": label, "base_size": "0.0000648950", "limit_price": "81664.97580", "trailing_stop": False},
            {"label": "TP2", "base_size": "0.0000324475", "limit_price": "82481.625558000", "trailing_stop": False},
            {"label": "RUNNER", "base_size": "0.0000324475", "trailing_stop": True},
        ],
    }


def _stores(tmp_path: Path):
    return (
        OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        StateStore(),
    )


class FakeCoinbaseClient:
    def __init__(self):
        self.calls = []

    def place_limit_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"order_id": "cb-d3-exit-1", "success": True}


def test_preview_mode_does_not_submit(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=False,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert report["live_submission_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["one_shot_actual_exit_submit_armed_process_local"] is False


def test_live_context_preview_uses_exchange_rules_and_changes_fingerprint(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    cfg = _cfg(monkeypatch)
    fallback = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules=None,
    )
    live_context = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    assert fallback["selected_plan_fingerprint"] != live_context["selected_plan_fingerprint"]
    assert fallback["selected_sell_base"] == "0.0000648950"
    assert live_context["selected_sell_base"] == "0.00006489"
    assert Decimal(live_context["selected_raw_limit_price"]) >= Decimal(live_context["selected_limit_price"])
    assert live_context["exchange_rules_context"] == "coinbase_live_product_rules"
    assert live_context["base_increment"] == "1E-8"
    assert live_context["price_increment"] == "0.01"
    assert live_context["min_order_quote"] == "1"
    assert live_context["live_submission_attempted"] is False
    assert live_context["live_order_submitted"] is False


def test_live_context_preview_blocks_when_required_fingerprint_does_not_match(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        require_plan_fingerprint="wrong-fp",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    assert report["selected_plan_fingerprint"] != "wrong-fp"
    assert "d3_pilot_plan_fingerprint_mismatch" in report["blockers"]
    assert "preview_only_submit_live_false" in report["warnings"]


def test_live_context_preview_blocks_when_rules_context_missing(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules=None,
        exchange_rules_context="coinbase_live_product_rules_fetch_failed",
        exchange_rules_fetch_error={"error_type": "RuntimeError", "error": "dns"},
    )
    assert "d3_pilot_live_exchange_rules_context_missing" in report["blockers"]
    assert "d3_pilot_live_exchange_rules_fetch_error:RuntimeError" in report["warnings"]


def test_live_context_preview_match_stays_ready_no_submit(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    cfg = _cfg(monkeypatch)
    report = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    matched = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        require_plan_fingerprint=report["selected_candidate_fingerprint"],
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    assert matched["status"] == "d3_controlled_exit_ready_no_submit"
    assert matched["selected_sell_base"] == "0.00006489"
    assert matched["selected_limit_price"] == report["selected_limit_price"]
    assert matched["selected_candidate_fingerprint"] == report["selected_candidate_fingerprint"]
    assert matched["selected_candidate_fingerprint_version"] == D3_CANDIDATE_FINGERPRINT_VERSION
    assert matched["live_submission_attempted"] is False
    assert matched["live_order_submitted"] is False


def test_d3_candidate_fingerprint_ignores_position_quote_notional(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    cfg = _cfg(monkeypatch)
    first = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position={**_position(), "position_size_quote": "9.99"},
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    second = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position={**_position(), "position_size_quote": "10.42"},
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    assert first["selected_plan_fingerprint"] != second["selected_plan_fingerprint"]
    assert first["selected_candidate_fingerprint"] == second["selected_candidate_fingerprint"]
    assert "position_size_quote" in first["fingerprint_excluded_fields"]


def test_d3_candidate_fingerprint_changes_for_semantic_candidate_fields():
    base_intent = {
        "ticker": "BTC-USDC",
        "position_id": "pos-live-1",
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "label": "TP1",
        "size_base": "0.00006489",
        "limit_price": "84800.00",
        "estimated_quote_value": "5.5026720000",
        "post_only": True,
        "reduce_only_local": True,
    }
    common = {
        "ticker": "BTC-USDC",
        "reservation_governance": {
            "available_base_after_reservations": "0.0001297967431275",
            "reserved_base_open_exit_orders": "0",
        },
        "open_d3_orders": {"total_open_d3_exit_orders": 0},
        "base_increment": "1E-8",
        "price_increment": "0.01",
        "quote_increment": "0.01",
        "min_order_quote": "1",
    }
    baseline = build_d3_candidate_fingerprint(selected_exit_intent=base_intent, **common)["fingerprint"]
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "size_base": "0.00006488", "estimated_quote_value": "5.501824"},
        **common,
    )["fingerprint"] != baseline
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "limit_price": "84799.99", "estimated_quote_value": "5.5026713511"},
        **common,
    )["fingerprint"] != baseline
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "position_id": "pos-live-2"},
        **common,
    )["fingerprint"] != baseline
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "side": "BUY"},
        **common,
    )["fingerprint"] != baseline
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "label": "TP2"},
        **common,
    )["fingerprint"] != baseline
    assert build_d3_candidate_fingerprint(
        selected_exit_intent={**base_intent, "execution_action": "noop"},
        **common,
    )["fingerprint"] != baseline


def test_live_context_preview_submit_reject_stays_not_submitted(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)

    class RejectingClient:
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

    cfg = _cfg(monkeypatch)
    preview = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=False,
        use_live_exchange_rules_preview=True,
        require_position_id="pos-live-1",
        order_store=order_store,
        state_store=state_store,
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    report = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=True,
        use_live_exchange_rules_preview=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_fingerprint=preview["selected_plan_fingerprint"],
        order_store=order_store,
        state_store=state_store,
        coinbase_client=RejectingClient(),
        position=_position(),
        exchange_rules={"quote_min_size": "1", "base_increment": "0.00000001", "quote_increment": "0.01"},
        exchange_rules_context="coinbase_live_product_rules",
    )
    assert report["submit_result"]["live_submission_attempted"] is True
    assert report["submit_result"]["live_order_submitted"] is False
    assert report["status"] == "d3_controlled_exit_pilot_live_order_rejected"
    assert order_store.open_exit_orders("BTC-USDC") == []


def test_one_shot_requires_exact_ack(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack="wrong",
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=client,
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert report["status"] == "d3_controlled_exit_pilot_blocked"
    assert "one_shot_actual_exit_submit_ack_missing_or_wrong" in report["one_shot_actual_exit_submit_blockers"]
    assert client.calls == []


def test_one_shot_requires_existing_d3_ack(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    client = FakeCoinbaseClient()
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack="wrong",
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=client,
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert report["status"] == "d3_controlled_exit_pilot_blocked"
    assert "d3_pilot_human_ack_missing_or_invalid" in report["blockers"]
    assert client.calls == []


def test_one_shot_blocks_non_btc_ticker(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="ETH-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position={**_position(), "ticker": "ETH-USDC"},
        plan={**_plan(), "ticker": "ETH-USDC"},
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_ticker_not_btc_usdc" in report["blockers"]


def test_one_shot_blocks_non_tp1_exit(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(label="TP_CLOSE"),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_selected_exit_not_tp1" in report["blockers"]


def test_one_shot_blocks_position_id_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="wrong-pos",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_position_id_mismatch" in report["blockers"]


def test_one_shot_blocks_plan_id_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="wrong-plan",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_plan_id_mismatch" not in report["blockers"]
    assert "d3_pilot_plan_id_trace_mismatch" in report["warnings"]


def test_submit_live_blocks_when_plan_fingerprint_missing(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_required_plan_fingerprint_missing" in report["blockers"]


def test_submit_live_blocks_when_plan_fingerprint_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="wrong-fp",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_plan_fingerprint_mismatch" in report["blockers"]


def test_one_shot_blocks_open_d3_exit_order(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-open",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-live-1",
        "execution_action": "place_limit_sell",
        "remaining_size": "0.0000648950",
        "d3_exit_label": "TP1",
    })
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_open_d3_exit_order_exists" in report["blockers"]


def test_one_shot_blocks_incoherent_reservation_governance(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1000.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_reservation_governance_not_coherent" in report["blockers"]


def test_one_shot_blocks_when_replication_enabled(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    report = build_controlled_exit_pilot_report(
        cfg=_cfg(monkeypatch, replication_enabled=True),
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert "d3_pilot_replication_enabled" in report["blockers"]


def test_one_shot_process_local_arming_does_not_mutate_original_cfg(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    cfg = _cfg(monkeypatch)
    assert cfg.enable_phase_d3_actual_exit_submit is False
    report = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=FakeCoinbaseClient(),
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert cfg.enable_phase_d3_actual_exit_submit is False
    assert cfg.enable_live_exit_orders is False
    assert cfg.autonomous_allow_exits is False
    assert cfg.phase_c_disable_exit_limit_orders is True
    assert report["one_shot_actual_exit_submit_armed_process_local"] is True
    assert report["one_shot_actual_exit_submit_env_mutation"] is False


def test_one_shot_success_path_calls_existing_d3_submit_once_with_fake_coinbase_client_only(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    order_store, state_store = _stores(tmp_path)
    cfg = _cfg(monkeypatch)
    client = FakeCoinbaseClient()

    import bot.phase_d3_controlled_exit_pilot as pilot_mod

    original = pilot_mod.submit_phase_d3_controlled_exit
    calls = {"count": 0}

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pilot_mod, "submit_phase_d3_controlled_exit", wrapped)

    report = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        submit_live=True,
        one_shot_actual_exit_submit=True,
        one_shot_arm_ack=ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK,
        d3_human_ack=D3_ACK,
        require_position_id="pos-live-1",
        require_plan_id="d2-BTC-USDC-fixed",
        require_plan_fingerprint="fp-1",
        order_store=order_store,
        state_store=state_store,
        coinbase_client=client,
        position=_position(),
        plan=_plan(),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
        audit_path=tmp_path / "audit.jsonl",
    )

    assert calls["count"] == 1
    assert report["live_order_submitted"] is True
    assert len(client.calls) == 1
