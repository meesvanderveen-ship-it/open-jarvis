from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.live_learning_orchestrator import build_live_learning_context, load_runtime_learning_context


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_missing_learning_files_continue_with_baseline_context(tmp_path: Path) -> None:
    report = build_live_learning_context(root=tmp_path, generated_at="2026-06-12T00:00:00Z")

    assert report["classification"] == "WATCH"
    assert report["runtime_context"]["safety_policy"]["soft_context_only"] is True
    assert report["runtime_context"]["safety_policy"]["parameter_mutation_allowed"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["llm_call_attempted"] is False


def test_corrupt_context_file_loads_safe_fallback(tmp_path: Path) -> None:
    path = tmp_path / "reports/live_learning/live-learning-context-latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")

    ctx = load_runtime_learning_context(root=tmp_path)

    assert ctx["classification"] == "WATCH"
    assert ctx["safety_policy"]["soft_context_only"] is True


def test_orchestrator_compacts_learning_sources(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/trade_reflections.jsonl").write_text(
        json.dumps({"reflection": {"avoid_conditions": ["wide spread chase"], "prefer_conditions": ["reclaim with volume"]}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "logs/execution_outcomes.jsonl").write_text(
        json.dumps({"primary_label": "missed_fill_opportunity", "labels": ["missed_fill_opportunity"]}) + "\n",
        encoding="utf-8",
    )
    _write(tmp_path / "reports/live_learning/start-parameter-candidates-latest.json", {"candidates": [{"profile_name": "p", "safe_to_activate_now": True}]})

    report = build_live_learning_context(root=tmp_path, generated_at="2026-06-12T00:00:00Z")

    runtime = report["runtime_context"]
    assert runtime["classification"] == "READY"
    assert runtime["top_avoid_lessons"] == ["wide spread chase"]
    assert runtime["top_prefer_lessons"] == ["reclaim with volume"]
    assert runtime["top_poor_execution_labels"] == ["missed_fill_opportunity:1"]
