from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_human_review_export import (
    build_phase_d6_human_review_export,
    human_review_export_to_markdown,
    write_human_review_export,
)
from bot.phase_d6_parameter_review_pack import build_phase_d6_parameter_review_pack


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_human_review_export_wraps_pack_and_markdown_is_safe():
    pack = build_phase_d6_parameter_review_pack()
    export = build_phase_d6_human_review_export(parameter_review_pack=pack)
    markdown = human_review_export_to_markdown(export)

    assert export["status"] == "d6_human_review_export_ready"
    assert export["explicit_conclusion"] == "no_parameter_changes_approved"
    assert "# D.6 Human Review Export" in markdown
    assert "No parameter changes approved." in markdown
    assert "best parameter" not in markdown.lower()
    assert "change parameter" not in markdown.lower()
    assert "recommendation" not in markdown.lower()
    _assert_safe(export)


def test_human_review_export_writes_only_reports_d6_outputs(tmp_path: Path):
    export = build_phase_d6_human_review_export(parameter_review_pack=build_phase_d6_parameter_review_pack())
    json_output = tmp_path / "reports" / "d6" / "review.json"
    md_output = tmp_path / "reports" / "d6" / "review.md"

    assert write_human_review_export(export, json_output) == json_output
    assert write_human_review_export(export, md_output, markdown=True) == md_output
    assert json.loads(json_output.read_text(encoding="utf-8"))["parameter_review_approved"] is False
    assert "No parameter changes approved." in md_output.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="reports_d6"):
        write_human_review_export(export, tmp_path / "reports" / "review.json")
    with pytest.raises(ValueError, match="state"):
        write_human_review_export(export, tmp_path / "state" / "review.json")


def test_human_review_export_cli_json_and_markdown_stdout(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    pack = build_phase_d6_parameter_review_pack()
    pack_path = _write_json(tmp_path / "research" / "pack.json", pack)

    json_result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_human_review_export.py", "--review-pack", str(pack_path)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    md_result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_human_review_export.py", "--review-pack", str(pack_path), "--markdown"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    export = json.loads(json_result.stdout)
    assert json_result.stderr == ""
    assert md_result.stderr == ""
    assert "# D.6 Human Review Export" in md_result.stdout
    _assert_safe(export)
