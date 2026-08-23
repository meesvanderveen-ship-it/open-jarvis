from dashboard.backend.services import run_summary as run_summary_service


def test_run_summary_merges_learning_evidence_notes_additively(monkeypatch):
    monkeypatch.setattr(run_summary_service.cache, "get_or_compute", lambda key, compute, ttl_seconds=None: compute())
    monkeypatch.setattr(run_summary_service, "run_json_tool", lambda script_name: {"phase": "latest_run_summary_v1", "summary_lines": ["1. ok"]})
    monkeypatch.setattr(run_summary_service, "get_learning_status", lambda: {"episode_count": 5})
    monkeypatch.setattr(
        run_summary_service,
        "get_learning_evidence_summary",
        lambda: {
            "decision_evidence_summary": ["10 resolved decision outcome(s)."],
            "run_evidence_summary": ["New resolved decision evidence since last check: 2."],
            "learning_evidence_summary": ["No parameter pressure changes detected since the last check."],
        },
    )

    result = run_summary_service.get_run_summary()

    assert result["phase"] == "latest_run_summary_v1"
    assert "learning_notes" in result
    assert result["decision_evidence_summary"] == ["10 resolved decision outcome(s)."]
    assert result["run_evidence_summary"] == ["New resolved decision evidence since last check: 2."]
    assert result["learning_evidence_summary"] == ["No parameter pressure changes detected since the last check."]


def test_run_summary_degrades_gracefully_when_evidence_tool_fails(monkeypatch):
    from dashboard.backend.services.shell_tool import ToolExecutionError

    monkeypatch.setattr(run_summary_service.cache, "get_or_compute", lambda key, compute, ttl_seconds=None: compute())
    monkeypatch.setattr(run_summary_service, "run_json_tool", lambda script_name: {"phase": "latest_run_summary_v1"})
    monkeypatch.setattr(run_summary_service, "get_learning_status", lambda: {})

    def _raise():
        raise ToolExecutionError("boom")

    monkeypatch.setattr(run_summary_service, "get_learning_evidence_summary", _raise)

    result = run_summary_service.get_run_summary()

    assert result["phase"] == "latest_run_summary_v1"
    assert result["learning_evidence_summary"] == ["Learning evidence summary unavailable this cycle."]
