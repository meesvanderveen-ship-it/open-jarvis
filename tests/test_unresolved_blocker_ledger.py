from __future__ import annotations

import json
from pathlib import Path

from bot.phase_unresolved_blocker_ledger import (
    build_unresolved_blocker_ledger,
    render_unresolved_blocker_ledger_markdown,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    _write(d6 / "d6-shadow-learning-report-20260609.json", {"phase": "shadow"})
    _write(d6 / "operator-24h-prerun-build-checklist-20260609.json", {"phase": "checklist"})
    _write(d6 / "all-ticker-24h-workflow-readiness-pack-20260609.json", {"phase": "all_ticker"})
    _write(d6 / "all-ticker-operator-preflight-command-pack-20260609.json", {"phase": "commands"})
    _write(d6 / "all-ticker-live-scope-guard-20260609.json", {"phase": "guard"})
    _write(d6 / "all-ticker-live-readonly-preflight-20260609.json", {"phase": "preflight"})
    _write(d6 / "shadow-parameter-approximation-pack-20260609.json", {"phase": "shadow_params"})


def test_ledger_separates_ack_live_external_and_complete_items(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_unresolved_blocker_ledger(root=tmp_path)
    categories = report["categories"]

    assert categories["blocked_by_ACK"]
    assert categories["blocked_by_live_fresh_preflight"]
    assert categories["blocked_by_external_follower_repo"]
    assert categories["blocked_by_live_position_fill_evidence"]
    assert categories["locally_complete"]


def test_ack_blockers_are_not_locally_buildable(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_unresolved_blocker_ledger(root=tmp_path)

    for row in report["categories"]["blocked_by_ACK"]:
        assert row["codex_can_build_more_now_without_ack_live_external_code"] is False


def test_external_follower_repo_is_external_blocker(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_unresolved_blocker_ledger(root=tmp_path)
    follower = [row for row in report["items"] if row["category"] == "follower/replication"][0]

    assert follower["blocker_type"] == "blocked_by_external_follower_repo"
    assert follower["blocks_full_workflow"] is True


def test_no_remaining_local_item_hidden_after_sources_exist(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    flags = build_unresolved_blocker_ledger(root=tmp_path)["governance_flags"]

    assert flags["unresolved_blocker_ledger_ready"] is True
    assert flags["remaining_locally_buildable_item_count"] == 0
    assert flags["all_remaining_items_are_ack_live_or_external_dependent"] is True


def test_missing_local_reports_show_remaining_local_work(tmp_path: Path) -> None:
    report = build_unresolved_blocker_ledger(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["governance_flags"]["remaining_locally_buildable_item_count"] > 0


def test_no_external_state_or_parameter_side_effects(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    meta = build_unresolved_blocker_ledger(root=tmp_path)["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False


def test_ledger_markdown_renders(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_unresolved_blocker_ledger_markdown(build_unresolved_blocker_ledger(root=tmp_path))

    assert "Unresolved Blocker Ledger" in markdown
    assert "remaining_locally_buildable_item_count" in markdown
