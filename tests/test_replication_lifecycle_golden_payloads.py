from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_replication_lifecycle_golden_payloads import (  # noqa: E402
    PHASE,
    build_negative_fixtures,
    build_positive_golden_sequence,
    build_replication_lifecycle_golden_payload_report,
    render_replication_lifecycle_golden_markdown,
)
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION, validate_lifecycle_event_v1  # noqa: E402
from tools.build_replication_lifecycle_golden_payloads import main  # noqa: E402


def _root(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "reports/d6").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text('{"BTC-USDC": {"position_size_base": "0"}}\n', encoding="utf-8")
    return tmp_path


def test_positive_golden_sequence_covers_required_master_lifecycle_events() -> None:
    events = build_positive_golden_sequence()
    event_types = [event["event_type"] for event in events]

    assert event_types == [
        "governance_status",
        "decision",
        "c4_entry_order",
        "c4_terminal_order",
        "d1_fill_to_position",
        "d2_position_plan",
        "d3_exit_preview",
        "d3_live_exit_intent",
        "d4_cancel_replace_trailing",
        "d5_execution_metric",
        "governance_status",
    ]
    for event in events:
        valid, errors, effect = validate_lifecycle_event_v1(event)
        assert valid is True, (event["event_id"], errors)
        assert event["schema_version"] == SCHEMA_VERSION
        assert event["source"] == "master"
        assert event["mode"] == "paper_observe"
        assert event["live_order_action"] is False
        assert event["state_mutation"] is False
        assert effect["live_order_action"] is False


def test_negative_fixture_names_are_complete_and_schema_valid_where_expected() -> None:
    fixtures = build_negative_fixtures()

    assert set(fixtures) == {
        "unsupported_ticker",
        "over_cap_notional",
        "duplicate_event_id",
        "d1_without_prior_fill",
        "d3_live_exit_without_ack",
        "d4_cancel_replace_without_ack",
        "no_oversell_violation",
    }
    for name, events in fixtures.items():
        assert events, name
        for event in events:
            valid, errors, _effect = validate_lifecycle_event_v1(event)
            assert valid is True, (name, event["event_id"], errors)


def test_golden_report_validates_payloads_and_simulator_fail_closed(tmp_path: Path) -> None:
    report = build_replication_lifecycle_golden_payload_report(root=_root(tmp_path))

    assert report["phase"] == PHASE
    assert report["lifecycle_payloads_valid"] is True
    assert report["positive_sequence_passed"] is True
    assert report["negative_fixtures_passed"] is True
    assert report["simulator_validation_passed"] is True
    assert report["follower_ready_for_live"] is False
    assert report["positive_simulator_report"]["live_order_attempted"] is False
    assert report["positive_simulator_report"]["coinbase_call_attempted"] is False
    assert report["positive_simulator_report"]["state_write_performed"] is False
    assert "d3_live_exit_intent_requires_separate_follower_ack" in report["positive_simulator_report"]["blockers"]
    assert "d4_cancel_replace_requires_separate_follower_ack" in report["positive_simulator_report"]["blockers"]

    negative = report["negative_simulator_results"]
    assert negative["unsupported_ticker"]["expectation_passed"] is True
    assert negative["over_cap_notional"]["expectation_passed"] is True
    assert negative["duplicate_event_id"]["expectation_passed"] is True
    assert negative["d1_without_prior_fill"]["expectation_passed"] is True
    assert negative["d3_live_exit_without_ack"]["expectation_passed"] is True
    assert negative["d4_cancel_replace_without_ack"]["expectation_passed"] is True
    assert negative["no_oversell_violation"]["expectation_passed"] is True
    assert "no_oversell_check_failed" in negative["no_oversell_violation"]["blockers"]


def test_markdown_and_cli_write_reports_without_state_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_replication_lifecycle_golden_payload_report(root=root)
    markdown = render_replication_lifecycle_golden_markdown(report)
    assert "# Replication Lifecycle Golden Payloads" in markdown
    assert "unsupported_ticker" in markdown

    monkeypatch.chdir(root)
    rc = main(
        [
            "--json-out",
            "reports/d6/replication-lifecycle-golden-payloads.json",
            "--markdown-out",
            "reports/d6/replication-lifecycle-golden-payloads.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/replication-lifecycle-golden-payloads.json").read_text(encoding="utf-8"))
    assert payload["phase"] == PHASE
    assert payload["simulator_validation_passed"] is True
    assert "Replication Lifecycle Golden Payloads" in (
        root / "reports/d6/replication-lifecycle-golden-payloads.md"
    ).read_text(encoding="utf-8")
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
