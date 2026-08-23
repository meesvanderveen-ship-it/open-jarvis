from dashboard.backend.services import run_summary as run_summary_service


def test_learning_notes_built_from_learning_status():
    notes = run_summary_service._learning_notes(
        {
            "episode_count": 2783,
            "new_memory_episodes": 5,
            "proposal_count": 1,
            "blocked_proposal_count": 0,
            "product_readiness": {"report_only_ready": True, "stabilization_ready": False},
        }
    )

    assert any("2783" in n for n in notes)
    assert any("1 active parameter proposal" in n for n in notes)
    assert any("report_only_ready" in n for n in notes)


def test_learning_notes_handles_empty_learning_status():
    notes = run_summary_service._learning_notes({})
    assert notes == ["No learning status available this run."]


def test_get_run_summary_merges_tool_output_with_learning_notes(monkeypatch):
    monkeypatch.setattr(
        run_summary_service,
        "run_json_tool",
        lambda script_name: {"phase": "latest_run_summary_v1", "overall_decision": "wait"},
    )
    monkeypatch.setattr(run_summary_service.cache, "get_or_compute", lambda key, compute, ttl_seconds=None: compute())
    monkeypatch.setattr(run_summary_service, "get_learning_status", lambda: {"episode_count": 10})

    result = run_summary_service.get_run_summary()

    assert result["overall_decision"] == "wait"
    assert "learning_notes" in result
    assert any("10" in n for n in result["learning_notes"])
