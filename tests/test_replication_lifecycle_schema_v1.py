from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_replication_lifecycle_schema_v1 import (  # noqa: E402
    PHASE,
    SCHEMA_VERSION,
    build_replication_lifecycle_schema_report,
    render_replication_lifecycle_schema_markdown,
    validate_lifecycle_event_v1,
)
from tools.build_replication_lifecycle_schema_report import main  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    _write(
        tmp_path / "replication/models.py",
        "class ReplicationEnvelope:\n    pass\n",
    )
    _write(
        tmp_path / "replication/publisher.py",
        "def publish_decision_best_effort(): pass\n"
        "url = f\"{self.config.replica_url}/api/replica/decision\"\n"
        "headers = {'x-replica-signature': 'sig'}\n",
    )
    _write(
        tmp_path / "run_trader_loop.py",
        "_replicate_full_cycle_results\n_replicate_heartbeat_results\n",
    )
    _write(tmp_path / "state/open_orders.json", '{"orders": {}}\n')
    _write(tmp_path / "state/positions.json", '{"BTC-USDC": {"position_size_base": "0"}}\n')
    (tmp_path / "reports/d6").mkdir(parents=True)
    return tmp_path


def _base_event(event_type: str) -> dict:
    return {
        "event_id": "evt-1",
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "source_bot": "server1-master",
        "ticker": "BTC-USDC",
        "governance": {
            "classification": "OK",
            "follower_default_mode": "paper_only",
            "live_action_authorized": False,
        },
    }


def test_decision_event_validates_as_paper_only() -> None:
    event = {
        **_base_event("decision"),
        "decision": "approve_trade",
        "side": "BUY",
    }

    valid, errors, effect = validate_lifecycle_event_v1(event)

    assert valid is True
    assert errors == []
    assert effect["accepted_for_transport"] is True
    assert effect["live_order_action"] is False
    assert effect["state_mutation"] is False


def test_all_lifecycle_events_are_non_live_by_default() -> None:
    event_payloads = [
        {**_base_event("c4_entry_order"), "order": {"status": "open"}},
        {**_base_event("c4_terminal_order"), "order": {"status": "filled"}, "fill": {"base_size": "0.001"}},
        {**_base_event("d1_fill_to_position"), "fill": {"base_size": "0.001"}, "position": {"status": "preview"}},
        {**_base_event("d2_position_plan"), "position": {"id": "pos-1"}, "plan": {"plan_fingerprint": "abc"}},
        {**_base_event("d3_exit_preview"), "position": {"id": "pos-1"}, "exit_preview": {"submit_live": False}},
        {
            **_base_event("d3_live_exit_intent"),
            "position": {"id": "pos-1"},
            "exit_intent": {"side": "SELL", "submit_live": False},
        },
        {
            **_base_event("d4_cancel_replace_trailing"),
            "replace_intent": {"cancel_live": False, "submit_live": False},
        },
        {**_base_event("d5_execution_metric"), "metric": {"name": "fill_latency_ms", "value": 1}},
        {**_base_event("governance_status"), "status": {"classification": "WATCH"}},
    ]

    for event in event_payloads:
        valid, errors, effect = validate_lifecycle_event_v1(event)
        assert valid is True, (event["event_type"], errors)
        assert effect["live_order_action"] is False
        assert effect["state_mutation"] is False


def test_d3_live_exit_intent_does_not_authorize_default_sell() -> None:
    event = {
        **_base_event("d3_live_exit_intent"),
        "position": {"id": "pos-1"},
        "exit_intent": {"side": "SELL", "submit_live": True},
    }

    valid, errors, effect = validate_lifecycle_event_v1(event)

    assert valid is False
    assert "d3_live_exit_intent_submit_live_forbidden_by_default" in errors
    assert effect["live_order_action"] is False
    assert effect["requires_human_review"] is True


def test_unknown_and_live_authorized_events_fail_closed() -> None:
    unknown = {**_base_event("future_event"), "extra": {"new": True}}
    valid, errors, effect = validate_lifecycle_event_v1(unknown)
    assert valid is False
    assert "unknown_event_type" in errors
    assert effect["live_order_action"] is False
    assert effect["accepted_for_transport"] is False

    d4 = {
        **_base_event("d4_cancel_replace_trailing"),
        "governance": {
            "classification": "OK",
            "follower_default_mode": "paper_only",
            "live_action_authorized": True,
        },
        "replace_intent": {"cancel_live": True, "submit_live": False},
    }
    valid, errors, effect = validate_lifecycle_event_v1(d4)
    assert valid is False
    assert "live_action_authorized_forbidden_in_schema_v1_default" in errors
    assert "d4_cancel_replace_live_action_forbidden_by_default" in errors
    assert effect["live_order_action"] is False


def test_report_and_cli_mark_readiness_false_without_state_writes(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_replication_lifecycle_schema_report(root=root)
    markdown = render_replication_lifecycle_schema_markdown(report)

    assert report["phase"] == PHASE
    assert report["current_architecture"]["current_replication_shape"] == "decision_only"
    assert report["readiness"]["follower_buy_ready"] is False
    assert report["readiness"]["follower_sell_ready"] is False
    assert report["readiness"]["lifecycle_parity_ready"] is False
    assert report["readiness"]["follower_ready_for_paper_lifecycle_test"] is True
    assert "Replication Lifecycle Schema V1" in markdown
    assert "d3_live_exit_intent" in markdown

    monkeypatch.chdir(root)
    rc = main(
        [
            "--json-out",
            "reports/d6/replication-lifecycle-schema-v1.json",
            "--markdown-out",
            "reports/d6/replication-lifecycle-schema-v1.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/replication-lifecycle-schema-v1.json").read_text(encoding="utf-8"))
    assert payload["phase"] == PHASE
    assert "Replication Lifecycle Schema V1" in (
        root / "reports/d6/replication-lifecycle-schema-v1.md"
    ).read_text(encoding="utf-8")
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
