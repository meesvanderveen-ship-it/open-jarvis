from dashboard.backend.services import parameter_proposal_funnel as funnel_service


def test_get_parameter_proposal_funnel_passes_through_tool_output(monkeypatch):
    monkeypatch.setattr(
        funnel_service.cache,
        "get_or_compute",
        lambda key, compute, ttl_seconds=None: compute(),
    )
    monkeypatch.setattr(
        funnel_service,
        "run_json_tool",
        lambda script_name: {
            "schema_version": "parameter_proposal_funnel_v1",
            "funnel_counts": {"observed_signal": 46, "apply_ready_candidate": 0},
            "total_parameters": 48,
        },
    )

    result = funnel_service.get_parameter_proposal_funnel()

    assert result["total_parameters"] == 48
    assert result["funnel_counts"]["apply_ready_candidate"] == 0


def test_router_raises_502_on_tool_execution_error(monkeypatch):
    from fastapi.testclient import TestClient

    from dashboard.backend.app import app
    from dashboard.backend.routers import parameter_proposal_funnel as router_module
    from dashboard.backend.services.shell_tool import ToolExecutionError

    def _raise():
        raise ToolExecutionError("boom")

    monkeypatch.setattr(router_module, "get_parameter_proposal_funnel", _raise)

    client = TestClient(app)
    response = client.get("/api/parameters/proposal-funnel")
    assert response.status_code == 502
