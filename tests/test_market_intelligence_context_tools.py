from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_tool_works_with_fixture_no_network(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_market_intelligence_context.py",
            "--root",
            str(tmp_path),
            "--no-network",
            "--json",
            "--json-out",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["available"] is True
    assert out.exists()
    assert (tmp_path / "state/market_intelligence_context.json").exists()


def test_show_tool_works(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "tools/build_market_intelligence_context.py", "--root", str(tmp_path), "--no-network"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, "tools/show_market_intelligence_context.py", "--root", str(tmp_path), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["source_policy"] == "context_only_no_order_authority"
    assert payload["can_authorize_execution"] is False
    assert payload["sources"]["defillama"] in {"available", "partial"}
    assert payload["sources"]["coinmetrics"] in {"available", "partial"}
    assert payload["sources"]["santiment"] == "disabled"
    assert isinstance(payload["warnings"], list)


def test_build_tool_source_selection_disables_unselected_santiment(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_market_intelligence_context.py",
            "--root",
            str(tmp_path),
            "--no-network",
            "--sources",
            "defillama,coinmetrics",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["santiment"]["available"] is False
    assert payload["santiment"]["reason"] == "source_not_selected"
