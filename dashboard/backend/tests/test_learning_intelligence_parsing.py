from dashboard.backend.services import learning_intelligence as learning_intelligence_service


def test_get_learning_intelligence_passes_through_tool_output(monkeypatch):
    monkeypatch.setattr(
        learning_intelligence_service.cache,
        "get_or_compute",
        lambda key, compute, ttl_seconds=None: compute(),
    )
    monkeypatch.setattr(
        learning_intelligence_service,
        "run_json_tool",
        lambda script_name: {
            "schema_version": "adaptive_learning_intelligence_v1",
            "parameter_evidence": [{"parameter": "MAX_SPREAD_PCT", "tier": "observed_signal"}],
            "proposal_maturity_funnel": {"observed_signal": 1},
        },
    )

    result = learning_intelligence_service.get_learning_intelligence()

    assert result["schema_version"] == "adaptive_learning_intelligence_v1"
    assert result["parameter_evidence"][0]["parameter"] == "MAX_SPREAD_PCT"


def test_router_raises_502_on_tool_execution_error(monkeypatch):
    from fastapi.testclient import TestClient

    from dashboard.backend.app import app
    from dashboard.backend.routers import learning_intelligence as router_module
    from dashboard.backend.services.shell_tool import ToolExecutionError

    def _raise():
        raise ToolExecutionError("boom")

    monkeypatch.setattr(router_module, "get_learning_intelligence", _raise)

    client = TestClient(app)
    response = client.get("/api/learning/intelligence")
    assert response.status_code == 502
