import json

from dashboard.backend.services import trace as trace_service


def test_builds_trace_steps_from_decision_record(monkeypatch, tmp_path):
    decision_path = tmp_path / "decision_outcomes.json"
    decision_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "ticker": "BTC-USDC",
                        "created_at": "2026-06-23T08:00:00Z",
                        "decision": "wait",
                        "entry_gate": {"decision": "analyze", "confidence": 60},
                        "trade_plan": {"plan_action": "prepare_buy"},
                        "judge": {"decision": "wait", "confidence": 55},
                        "chart_patterns": {"summary": "pattern"},
                        "growbot_river_learning_context": {"regime": "trend_up"},
                    },
                    {
                        "ticker": "ETH-USDC",
                        "created_at": "2026-06-23T08:00:00Z",
                        "decision": "wait",
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(trace_service, "resolve_state_file", lambda name: decision_path)
    monkeypatch.setattr(trace_service, "get_positions", lambda: {"positions": []})
    monkeypatch.setattr(trace_service, "get_orders", lambda: {"orders": []})

    result = trace_service.get_ticker_trace("BTC-USDC")

    assert result["decision"] == "wait"
    steps_by_id = {s["step"]: s for s in result["steps"]}
    assert steps_by_id["hard_gate"]["status"] == "ok"
    assert steps_by_id["judge"]["summary"]["confidence"] == 55
    assert steps_by_id["risk_and_planning"]["status"] == "no_open_position"
    assert steps_by_id["learning_context"]["summary"]["regime"] == "trend_up"
    assert steps_by_id["reflection"]["status"] == "no_data"


def test_handles_unknown_ticker(monkeypatch, tmp_path):
    decision_path = tmp_path / "decision_outcomes.json"
    decision_path.write_text(json.dumps({"records": []}))
    monkeypatch.setattr(trace_service, "resolve_state_file", lambda name: decision_path)
    monkeypatch.setattr(trace_service, "get_positions", lambda: {"positions": []})
    monkeypatch.setattr(trace_service, "get_orders", lambda: {"orders": []})

    result = trace_service.get_ticker_trace("DOES-NOTEXIST")

    assert result["decision"] is None
    assert all(s["status"] in ("no_data", "no_open_position", "no_orders") for s in result["steps"])
