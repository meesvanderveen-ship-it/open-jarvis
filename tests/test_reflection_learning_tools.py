from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True, check=True)


def test_build_tool_fixture_no_network_writes_reports(tmp_path: Path) -> None:
    result = _run(["tools/build_reflection_learning_report.py", "--fixture-only", "--no-network", "--json", "--root", str(tmp_path)], ROOT)
    payload = json.loads(result.stdout)
    assert payload["read_only"] is True
    assert payload["can_authorize_execution"] is False
    assert (tmp_path / "reports/reflection/reflection-learning-latest.json").exists()
    assert (tmp_path / "reports/reflection/reflection-learning-latest.md").exists()
    assert (tmp_path / "reports/reflection/missed-opportunities-latest.json").exists()
    assert (tmp_path / "state/reflection_learning_context.json").exists()


def test_show_tool_works_without_state(tmp_path: Path) -> None:
    result = _run(["tools/show_reflection_learning_status.py", "--json", "--root", str(tmp_path)], ROOT)
    payload = json.loads(result.stdout)
    assert payload["available"] is False
    assert payload["can_block_execution"] is False


def test_show_tool_works_with_state(tmp_path: Path) -> None:
    _run(["tools/build_reflection_learning_report.py", "--fixture-only", "--no-network", "--root", str(tmp_path)], ROOT)
    result = _run(["tools/show_reflection_learning_status.py", "--json", "--root", str(tmp_path)], ROOT)
    payload = json.loads(result.stdout)
    assert "summary" in payload
    assert payload["can_authorize_execution"] is False


def test_summarize_missed_opportunities_json(tmp_path: Path) -> None:
    _run(["tools/build_reflection_learning_report.py", "--fixture-only", "--no-network", "--root", str(tmp_path)], ROOT)
    result = _run(["tools/summarize_missed_opportunities.py", "--json", "--root", str(tmp_path)], ROOT)
    payload = json.loads(result.stdout)
    assert "count" in payload
    assert isinstance(payload["items"], list)


def test_write_audit_tool_records_safety_policy(tmp_path: Path) -> None:
    result = _run(["tools/write_reflection_learning_audit.py", "--json", "--root", str(tmp_path)], ROOT)
    payload = json.loads(result.stdout)
    assert payload["safety_policy"]["no_coinbase_actions"] is True
    assert payload["safety_policy"]["no_env_mutation"] is True
    assert (tmp_path / "reports/audits/reflection-learning-context-latest.json").exists()
    assert (tmp_path / "reports/audits/reflection-learning-context-latest.md").exists()
