from __future__ import annotations

import json
from pathlib import Path

from tools.build_neural_training_dataset import build_neural_training_dataset


def test_missing_files_build_empty_dataset(tmp_path: Path) -> None:
    report = build_neural_training_dataset(root=tmp_path)
    assert report["sample_count"] == 0
    assert (tmp_path / "reports/live_learning/neural-training-dataset-latest.jsonl").exists()
    assert report["coinbase_call_attempted"] is False
    assert report["llm_call_attempted"] is False


def test_corrupt_jsonl_lines_are_skipped_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "logs/decision_outcomes.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"ticker": "BTC-USDC", "action_taken": "wait", "outcome": {"adverse_move": True}}) + "\n"
        + "{bad json\n",
        encoding="utf-8",
    )
    report = build_neural_training_dataset(root=tmp_path)
    source = report["sources"]["logs/decision_outcomes.jsonl"]
    assert source["records_loaded"] == 1
    assert source["corrupt_records"] == 1
    assert report["sample_count"] == 1
