from __future__ import annotations

from dashboard.backend.services import llm_cost as llm_cost_service


def _no_cache(key, compute, ttl_seconds=None):
    return compute()


def test_get_llm_cost_24h_passes_through_tool_output_and_uses_fixed_since(monkeypatch):
    monkeypatch.setattr(llm_cost_service.cache, "get_or_compute", _no_cache)
    seen_args = {}

    def _fake_run_json_tool(script_name, extra_args=None):
        seen_args["script_name"] = script_name
        seen_args["extra_args"] = extra_args
        return {"total_calls": 3, "total_estimated_cost_usd": 0.01}

    monkeypatch.setattr(llm_cost_service, "run_json_tool", _fake_run_json_tool)

    result = llm_cost_service.get_llm_cost_24h()

    assert result["total_calls"] == 3
    assert seen_args["script_name"] == "show_llm_cost_breakdown.py"
    assert seen_args["extra_args"] == ["--since", "24h"]


def test_get_llm_cost_7d_uses_fixed_since_window(monkeypatch):
    monkeypatch.setattr(llm_cost_service.cache, "get_or_compute", _no_cache)
    seen_args = {}

    def _fake_run_json_tool(script_name, extra_args=None):
        seen_args["extra_args"] = extra_args
        return {}

    monkeypatch.setattr(llm_cost_service, "run_json_tool", _fake_run_json_tool)
    llm_cost_service.get_llm_cost_7d()
    assert seen_args["extra_args"] == ["--since", "7d"]


def test_get_multi_agent_prompt_audit_passes_through(monkeypatch):
    monkeypatch.setattr(llm_cost_service.cache, "get_or_compute", _no_cache)
    monkeypatch.setattr(
        llm_cost_service,
        "run_json_tool",
        lambda script_name, extra_args=None: {"conclusion": {"multi_agent_system_correctness": "working_as_designed"}},
    )
    result = llm_cost_service.get_multi_agent_prompt_audit()
    assert result["conclusion"]["multi_agent_system_correctness"] == "working_as_designed"


def test_llm_cost_router_returns_502_on_tool_execution_error(monkeypatch):
    from fastapi.testclient import TestClient

    from dashboard.backend.app import app
    from dashboard.backend.routers import llm_cost as router_module
    from dashboard.backend.services.shell_tool import ToolExecutionError

    def _raise():
        raise ToolExecutionError("boom")

    monkeypatch.setattr(router_module, "get_llm_cost_24h", _raise)
    monkeypatch.setattr(router_module, "get_llm_cost_7d", _raise)
    monkeypatch.setattr(router_module, "get_multi_agent_prompt_audit", _raise)

    client = TestClient(app)
    assert client.get("/api/llm/cost").status_code == 502
    assert client.get("/api/llm/cost/7d").status_code == 502
    assert client.get("/api/llm/multi-agent-audit").status_code == 502


def test_llm_cost_endpoints_respond_with_real_tools():
    """End-to-end smoke test against the real tools/show_llm_cost_breakdown.py
    and tools/build_multi_agent_prompt_audit.py -- confirms the dashboard
    wiring actually works, not just the monkeypatched unit tests above."""
    from fastapi.testclient import TestClient

    from dashboard.backend.app import app

    client = TestClient(app)
    cost_response = client.get("/api/llm/cost")
    assert cost_response.status_code == 200
    body = cost_response.json()
    assert body["read_only"] is True
    assert "by_agent" in body

    audit_response = client.get("/api/llm/multi-agent-audit")
    assert audit_response.status_code == 200
    audit_body = audit_response.json()
    assert audit_body["read_only"] is True
    assert audit_body["llm_layer_count"] > 0
