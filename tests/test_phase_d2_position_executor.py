from types import SimpleNamespace
from pathlib import Path

from bot.phase_d2_position_executor import (
    D2_PLAN_STATUS_BLOCKED,
    D2_PLAN_STATUS_NO_POSITION,
    D2_PLAN_STATUS_READY,
    assess_minimum_net_edge,
    build_d2_exit_market_context,
    build_d2_plan_fingerprint,
    build_multi_exit_bracket_lite_plan,
    build_phase_d2_position_executor_report,
    load_position_executor_plans,
    save_position_executor_plan,
)


def _cfg(**overrides):
    base = dict(
        enable_phase_d2_position_executor=True,
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
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        phase_c_disable_exit_limit_orders=True,
        min_live_order_quote_usdc="20.00",
        max_live_order_quote_usdc="100.00",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _position(**overrides):
    base = dict(
        ticker="ADA-USDC",
        status="open",
        order_id="phasec-ADAUSDC-entry-1",
        entry_price="0.2500",
        position_size_base="100",
        position_size_quote="25.00",
        stop_price="0.2450",
        invalidation_price="0.2450",
    )
    base.update(overrides)
    return base


def test_minimum_net_edge_blocks_too_small_target_after_fees():
    result = assess_minimum_net_edge(cfg=_cfg(), entry_price="100", target_price="101", stop_price="98")
    assert result["status"] == "net_edge_blocked"
    assert "expected_net_edge_too_low" in result["blockers"]
    assert "reward_to_fee_ratio_too_low" in result["blockers"]


def test_minimum_net_edge_passes_when_reward_clearly_exceeds_cost_and_risk():
    result = assess_minimum_net_edge(cfg=_cfg(), entry_price="100", target_price="105", stop_price="98")
    assert result["status"] == "net_edge_pass"
    assert "expected_net_edge_above_minimum" in result["passed"]
    assert "reward_to_fee_ratio_above_minimum" in result["passed"]
    assert "reward_to_risk_ratio_above_minimum" in result["passed"]


def test_multi_exit_plan_never_exceeds_position_base_and_uses_tp_runner():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position(position_size_base="400", position_size_quote="100.00"))
    assert plan["status"] == D2_PLAN_STATUS_READY
    assert len(plan["exits"]) == 3
    total_base = sum(float(x["base_size"]) for x in plan["exits"])
    assert total_base <= 400.0
    assert any(x["label"] == "RUNNER" and x["trailing_stop"] for x in plan["exits"])
    assert plan["safety_policy"]["d2_does_not_submit_live_sell_orders"] is True


def test_small_position_fallback_reduces_exit_count_when_min_order_quote_would_fail():
    plan = build_multi_exit_bracket_lite_plan(
        cfg=_cfg(),
        position=_position(position_size_base="2", position_size_quote="0.50"),
        exchange_rules={"quote_min_size": "1.00"},
    )
    assert plan["status"] in {D2_PLAN_STATUS_READY, D2_PLAN_STATUS_BLOCKED}
    assert len(plan["exits"]) <= 2
    assert any("small_position_fallback" in warning for warning in plan["warnings"])


def test_position_around_min_live_quote_uses_full_close_not_dust_partials():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position(position_size_base="100", position_size_quote="25.00"))
    assert plan["status"] == D2_PLAN_STATUS_READY
    assert len(plan["exits"]) <= 1
    assert all(float(exit_["estimated_quote"]) >= 20.0 or exit_["label"] == "TP_CLOSE" for exit_ in plan["exits"])


class _EmptyStateStore:
    def get_position(self, ticker):
        return None
    def get_positions(self):
        return {}


def test_report_without_open_position_is_safe_no_submit():
    report = build_phase_d2_position_executor_report(cfg=_cfg(), ticker="BTC-USDC", state_store=_EmptyStateStore())
    assert report["status"] == D2_PLAN_STATUS_NO_POSITION
    assert report["live_sell_submit_attempted_by_this_tool"] is False
    assert report["live_sell_order_submitted"] is False
    assert "selected_open_position_not_found" in report["blockers"]


def test_report_with_position_returns_ready_plan_but_no_live_sell_submit():
    report = build_phase_d2_position_executor_report(cfg=_cfg(), ticker="ADA-USDC", position=_position())
    assert report["status"] == D2_PLAN_STATUS_READY
    assert report["plan_ready_no_live_exit_submit"] is True
    assert report["live_sell_submit_attempted_by_this_tool"] is False
    assert report["live_sell_order_submitted"] is False


def test_d2_blocks_plan_when_stop_or_invalidation_missing():
    plan = build_multi_exit_bracket_lite_plan(
        cfg=_cfg(),
        position=_position(stop_price="0", invalidation_price="0"),
    )
    assert plan["status"] == D2_PLAN_STATUS_BLOCKED
    assert "position_risk_incomplete_stop_or_invalidation_missing" in plan["blockers"]
    assert plan["protective_risk_state"]["status"] == "position_risk_incomplete"


def test_plan_store_roundtrip(tmp_path: Path):
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    path = tmp_path / "plans.json"
    save_position_executor_plan(plan, path)
    data = load_position_executor_plans(path)
    assert "ADA-USDC" in data["plans"]
    assert data["plans"]["ADA-USDC"]["status"] == D2_PLAN_STATUS_READY


def test_report_persisted_fields_are_exposed(tmp_path: Path):
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="ADA-USDC",
        position=_position(order_id="phasec-ADAUSDC-entry-1", phase_c43_client_order_id="phasec-ADAUSDC-entry-1"),
        persist_plan=True,
        plans_path=tmp_path / "plans.json",
        audit_path=tmp_path / "audit.jsonl",
    )
    assert report["persisted"] is True
    assert report["persisted_ticker_key"] == "ADA-USDC"
    assert report["linked_position_id"] == "phasec-ADAUSDC-entry-1"
    assert report["source_client_order_id"] == "phasec-ADAUSDC-entry-1"


def test_same_plan_content_can_change_plan_id_but_keep_fingerprint():
    plan1 = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    plan2 = dict(plan1)
    plan2["plan_id"] = "d2-ADA-USDC-other"
    plan2["generated_at"] = "2099-01-01T00:00:00+00:00"
    fp1 = build_d2_plan_fingerprint(plan1)
    fp2 = build_d2_plan_fingerprint(plan2)
    assert plan1["plan_id"] != plan2["plan_id"]
    assert fp1["plan_fingerprint"] == fp2["plan_fingerprint"]


def test_changing_tp1_limit_price_changes_fingerprint():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    changed = json_clone(plan)
    changed["exits"][0]["limit_price"] = "0.3000"
    assert build_d2_plan_fingerprint(plan)["plan_fingerprint"] != build_d2_plan_fingerprint(changed)["plan_fingerprint"]


def test_changing_stop_changes_fingerprint():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    changed = json_clone(plan)
    changed["risk"]["initial_stop_price"] = "0.2400"
    changed["risk"]["invalidation_price"] = "0.2400"
    assert build_d2_plan_fingerprint(plan)["plan_fingerprint"] != build_d2_plan_fingerprint(changed)["plan_fingerprint"]


def test_changing_base_size_changes_fingerprint():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    changed = json_clone(plan)
    changed["entry"]["base_size"] = "99"
    assert build_d2_plan_fingerprint(plan)["plan_fingerprint"] != build_d2_plan_fingerprint(changed)["plan_fingerprint"]


def test_fingerprint_excludes_plan_id_and_generated_at_fields():
    plan = build_multi_exit_bracket_lite_plan(cfg=_cfg(), position=_position())
    changed = json_clone(plan)
    changed["plan_id"] = "different-id"
    changed["generated_at"] = "different-time"
    assert build_d2_plan_fingerprint(plan)["plan_fingerprint"] == build_d2_plan_fingerprint(changed)["plan_fingerprint"]
    assert "plan_id" not in build_d2_plan_fingerprint(plan)["plan_fingerprint"]


def json_clone(value):
    import json

    return json.loads(json.dumps(value))


def test_build_d2_exit_market_context_empty_without_client():
    assert build_d2_exit_market_context("BTC-USDC") == {}


def test_build_d2_exit_market_context_fails_safe_on_market_data_error(monkeypatch):
    class BoomMarketDataService:
        def __init__(self, client):
            pass

        def build_feature_pack(self, ticker):
            raise RuntimeError("no candles available")

    monkeypatch.setattr("bot.market_data.MarketDataService", BoomMarketDataService)
    assert build_d2_exit_market_context("BTC-USDC", coinbase_client=object()) == {}


def test_build_d2_exit_market_context_extracts_resistance_and_support(monkeypatch):
    class FakeMarketDataService:
        def __init__(self, client):
            self.client = client

        def build_feature_pack(self, ticker):
            return {"ticker": ticker, "structure": {"nearest_resistance": 0.30, "nearest_support": 0.24}}

    monkeypatch.setattr("bot.market_data.MarketDataService", FakeMarketDataService)
    context = build_d2_exit_market_context("ADA-USDC", coinbase_client=object())
    assert context["nearest_resistance"] == 0.30
    assert context["nearest_support"] == 0.24
    assert context["market_structure"]["resistance_level"] == 0.30
    assert context["market_structure"]["support_level"] == 0.24


def test_market_context_resistance_target_used_over_position_fallback():
    # Real SOL-USDC-shaped gap: the static position take_profit_price (a fixed
    # 2x-risk multiple) is too close to clear the fee-edge gate, but live
    # resistance sits far enough away to clear it comfortably.
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="ADA-USDC",
        position=_position(take_profit_price="0.2550"),  # too close: would stay blocked
        market_context={"nearest_resistance": "0.30", "nearest_support": "0.24"},
    )
    assert report["status"] == D2_PLAN_STATUS_READY
    assert report["plan"]["exit_target_source_policy"]["target_source"] == "indicator_resistance_target"
    assert report["plan"]["exit_target_source_policy"]["used_market_context"] is True


def test_market_context_missing_still_falls_back_to_position_take_profit_price():
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="ADA-USDC",
        position=_position(take_profit_price="0.2550"),
    )
    assert report["plan"]["exit_target_source_policy"]["target_source"] == "position_take_profit_price"
    assert report["plan"]["exit_target_source_policy"]["used_market_context"] is False
