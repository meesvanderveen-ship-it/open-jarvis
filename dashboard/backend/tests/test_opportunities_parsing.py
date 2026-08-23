import json

from dashboard.backend.services import opportunities as opportunities_service


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


def test_handles_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(opportunities_service, "resolve_state_file", lambda name: missing)

    result = opportunities_service._compute_opportunities()

    assert result["opportunities"] == []
    assert result["summary"]["ticker_count"] == 0
