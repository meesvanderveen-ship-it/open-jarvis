from __future__ import annotations

from datetime import datetime, timezone

from bot.opportunity_memory import build_opportunity_from_analysis, evaluate_opportunities, load_opportunity_memory, upsert_opportunity


def test_opportunity_memory_promotes_only_when_trigger_reached(tmp_path):
    path = tmp_path / "opportunity_memory.json"
    now = datetime(2026, 6, 17, tzinfo=timezone.utc)
    opp = build_opportunity_from_analysis(
        ticker="xrp/usdc",
        analysis={"trade_plan": {"setup_type": "reclaim", "trigger_price": "1.25", "invalidation_level": "1.10"}},
        source_decision_id="decision-1",
        now=now,
    )
    result = upsert_opportunity(opp, path=path, max_opportunities=5)
    assert result["stored"] is True
    low = evaluate_opportunities(market_by_ticker={"XRP-USDC": {"mid_price": "1.20"}}, path=path, now=now)
    assert low["promotions"] == []
    high = evaluate_opportunities(market_by_ticker={"XRP-USDC": {"mid_price": "1.26"}}, path=path, now=now)
    assert high["promotions"][0]["action"] == "promote_to_judge_orderbook"
    assert high["live_order_authorized"] is False


def test_opportunity_memory_invalidates_and_uses_atomic_json(tmp_path):
    path = tmp_path / "opportunity_memory.json"
    now = datetime(2026, 6, 17, tzinfo=timezone.utc)
    opp = build_opportunity_from_analysis(
        ticker="SOL-USDC",
        analysis={"trade_plan": {"setup_type": "retest", "trigger_price": "150", "invalidation_level": "130"}},
        source_decision_id="decision-2",
        now=now,
    )
    upsert_opportunity(opp, path=path)
    report = evaluate_opportunities(market_by_ticker={"SOL-USDC": {"mid_price": "129"}}, path=path, now=now, persist=True)
    assert report["actions"][0]["action"] == "remove_invalidated"
    assert load_opportunity_memory(path)["opportunities"][0]["status"] == "invalidated"
