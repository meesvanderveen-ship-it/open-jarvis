import json

from dashboard.backend.services import opportunities as opportunities_service
from dashboard.backend.services import ticker_universe


def test_keeps_latest_record_per_ticker_and_computes_score(monkeypatch, tmp_path):
    fixture = {
        "records": [
            {
                "ticker": "BTC-USDC",
                "created_at": "2026-06-23T08:00:00Z",
                "decision": "wait",
                "judge": {"confidence": 50},
                "entry_gate": {"confidence": 40, "setup_type": "range"},
                "chart_patterns": {"best_pattern_score": 30, "summary": "old"},
            },
            {
                "ticker": "BTC-USDC",
                "created_at": "2026-06-23T09:00:00Z",
                "decision": "prepare_buy",
                "judge": {"confidence": 70},
                "entry_gate": {"confidence": 60, "setup_type": "breakout"},
                "chart_patterns": {"best_pattern_score": 80, "summary": "fresh"},
                "trade_plan": {"trigger": "close above resistance"},
            },
            {
                "ticker": "ETH-USDC",
                "created_at": "2026-06-23T09:30:00Z",
                "decision": "close_position",
                "judge": {"confidence": 90},
                "entry_gate": {},
                "chart_patterns": {},
            },
        ]
    }
    path = tmp_path / "decision_outcomes.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(opportunities_service, "resolve_state_file", lambda name: path)

    result = opportunities_service._compute_opportunities()

    assert result["summary"]["ticker_count"] == 2
    by_ticker = {o["ticker"]: o for o in result["opportunities"]}
    assert by_ticker["BTC-USDC"]["decision"] == "prepare_buy"
    assert by_ticker["BTC-USDC"]["reason"] == "close above resistance"
    assert by_ticker["BTC-USDC"]["opportunity_score"] == 70.0
    assert by_ticker["ETH-USDC"]["decision"] == "close_position"


def test_hides_opportunities_outside_ticker_universe(monkeypatch, tmp_path):
    fixture = {
        "records": [
            {"ticker": "BTC-USDC", "created_at": "2026-06-23T09:00:00Z", "decision": "wait"},
            {"ticker": "XRP-USDC", "created_at": "2026-06-23T09:00:00Z", "decision": "wait"},
        ]
    }
    path = tmp_path / "decision_outcomes.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(opportunities_service, "resolve_state_file", lambda name: path)
    universe_path = tmp_path / "runtime_ticker_universe.json"
    universe_path.write_text(json.dumps({"configured_ticker_universe": ["BTC-USDC"]}))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: universe_path)

    result = opportunities_service._compute_opportunities()

    tickers = {o["ticker"] for o in result["opportunities"]}
    assert tickers == {"BTC-USDC"}


def test_handles_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(opportunities_service, "resolve_state_file", lambda name: missing)

    result = opportunities_service._compute_opportunities()

    assert result["opportunities"] == []
    assert result["summary"]["ticker_count"] == 0


def test_proximity_trigger_ready_forces_green_regardless_of_gate_level():
    # A "watch"-level gate would otherwise score in the orange band, but a
    # ready trigger means the setup's own conditions are already met --
    # only a fresh judge pass stands between here and an order.
    record = {
        "decision": "wait",
        "entry_gate": {"decision": "watch", "confidence": 55, "setup_type": "reclaim_reversal"},
        "judge": {"confidence": 60},
        "pending_trade_plan": {"status": "trigger_ready", "trigger_ready": True},
        "chart_patterns": {"market_structure": {}},
    }
    proximity = opportunities_service._proximity(record)
    assert proximity["zone"] == "green"
    assert proximity["score"] >= 70
    assert any("Trigger" in c for c in proximity["conditions"])


def test_proximity_skip_gate_with_low_confidence_is_red():
    record = {
        "decision": "wait",
        "entry_gate": {"decision": "skip", "confidence": 20},
        "judge": {"confidence": 25},
        "pending_trade_plan": {},
        "chart_patterns": {"market_structure": {}},
    }
    proximity = opportunities_service._proximity(record)
    assert proximity["zone"] == "red"
    assert proximity["score"] < 40


def test_proximity_reject_decision_is_capped_low_even_with_strong_gate():
    record = {
        "decision": "reject",
        "entry_gate": {"decision": "priority_analyze", "confidence": 90},
        "judge": {"confidence": 85},
        "pending_trade_plan": {},
        "chart_patterns": {"market_structure": {"range_position": "near_support"}},
    }
    proximity = opportunities_service._proximity(record)
    assert proximity["zone"] == "red"
    assert proximity["conditions"][0] == "Beslissing: reject"


def test_proximity_near_support_nudges_score_up_over_mid_range():
    base = {
        "decision": "wait",
        "entry_gate": {"decision": "analyze", "confidence": 60},
        "judge": {"confidence": 60},
        "pending_trade_plan": {},
    }
    near = opportunities_service._proximity({
        **base,
        "chart_patterns": {"market_structure": {"distance_to_support_pct": 0.5, "range_position": "near_support"}},
    })
    far = opportunities_service._proximity({
        **base,
        "chart_patterns": {"market_structure": {"distance_to_support_pct": 10.0, "range_position": "mid_range"}},
    })
    assert near["score"] > far["score"]


def test_proximity_included_in_opportunity_and_conditions_are_short():
    record = {
        "ticker": "BTC-USDC",
        "decision": "wait",
        "entry_gate": {"decision": "analyze", "confidence": 57, "setup_type": "reclaim_reversal"},
        "judge": {"confidence": 72},
        "pending_trade_plan": {"status": "waiting", "trigger_ready": False},
        "chart_patterns": {
            "market_structure": {
                "distance_to_support_pct": 0.94,
                "distance_to_resistance_pct": 3.14,
                "range_position": "near_support",
                "breakout_status": "none",
            }
        },
    }
    opportunity = opportunities_service._build_opportunity(record)
    assert "proximity" in opportunity
    assert 0 <= opportunity["proximity"]["score"] <= 100
    assert len(opportunity["proximity"]["conditions"]) <= 5
