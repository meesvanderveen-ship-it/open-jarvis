from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION  # noqa: E402
from bot.phase_replication_paper_lifecycle_simulator import (  # noqa: E402
    PHASE,
    PaperLifecycleConfig,
    demo_fixture_events,
    render_paper_lifecycle_markdown,
    run_paper_lifecycle_simulation,
)
from tools.run_replication_paper_lifecycle_simulator import main  # noqa: E402


def _gov(classification: str = "OK") -> dict:
    return {
        "classification": classification,
        "follower_default_mode": "paper_only",
        "live_action_authorized": False,
    }


def _event(event_id: str, event_type: str, **extra: object) -> dict:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "source_bot": "server1-master",
        "ticker": "BTC-USDC",
        "governance": _gov(),
        **extra,
    }


def test_demo_sequence_consumes_full_lifecycle_paper_only() -> None:
    report = run_paper_lifecycle_simulation(demo_fixture_events())

    assert report["phase"] == PHASE
    assert report["paper_lifecycle_simulator_ready"] is True
    assert report["follower_ready_for_paper_lifecycle_test"] is True
    assert report["follower_ready_for_live"] is False
    assert report["live_order_attempted"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["summary"]["paper_order_count"] == 1
    assert report["summary"]["paper_position_count"] == 1
    assert report["summary"]["paper_d2_plan_count"] == 1
    assert report["summary"]["paper_d3_preview_count"] == 1
    assert report["summary"]["duplicate_ignored_count"] == 1
    assert "d3_live_exit_intent_requires_separate_follower_ack" in report["blockers"]
    assert "d4_cancel_replace_requires_separate_follower_ack" in report["blockers"]
    assert any(row["reason"] == "entry_order_above_max_notional" for row in report["rejected_events"])
    assert any(row["reason"] == "unsupported_ticker" for row in report["rejected_events"])


def test_d3_live_exit_intent_and_d4_live_flags_do_not_create_live_action() -> None:
    d3 = _event(
        "d3-1",
        "d3_live_exit_intent",
        position={"position_id": "paper-BTC-USDC"},
        exit_intent={"side": "SELL", "base_size": "1", "submit_live": False},
    )
    d4 = _event(
        "d4-1",
        "d4_cancel_replace_trailing",
        replace_intent={"cancel_live": True, "submit_live": False},
    )

    report = run_paper_lifecycle_simulation([d3, d4])

    assert report["live_order_attempted"] is False
    assert report["summary"]["paper_order_count"] == 0
    assert report["summary"]["paper_position_count"] == 0
    assert "no_oversell_check_failed" in report["blockers"]
    assert "d3_live_exit_intent_requires_separate_follower_ack" in report["blockers"]
    assert any(row["reason"] == "schema_validation_failed" for row in report["rejected_events"])


def test_caps_ticker_balance_and_max_open_orders_fail_closed() -> None:
    config = PaperLifecycleConfig(max_notional_quote=__import__("decimal").Decimal("10"), max_open_orders=1)
    good = _event("entry-1", "c4_entry_order", order={"order_id": "o1", "status": "open", "notional_quote": "5"})
    too_many = _event("entry-2", "c4_entry_order", order={"order_id": "o2", "status": "open", "notional_quote": "5"})
    over_cap = _event("entry-3", "c4_entry_order", order={"order_id": "o3", "status": "open", "notional_quote": "11"})
    unsupported = {**_event("entry-4", "c4_entry_order", order={"order_id": "o4", "status": "open", "notional_quote": "5"}), "ticker": "ETH-USDC"}

    report = run_paper_lifecycle_simulation([good, too_many, over_cap, unsupported], config=config)

    assert report["summary"]["paper_order_count"] == 1
    reasons = {row["reason"] for row in report["rejected_events"]}
    assert "max_open_paper_orders_exceeded" in reasons
    assert "entry_order_above_max_notional" in reasons
    assert "unsupported_ticker" in reasons


def test_d1_requires_prior_fill_evidence_and_stop_now_blocks_later_transition() -> None:
    d1 = _event(
        "d1-1",
        "d1_fill_to_position",
        fill={"order_id": "missing-order", "base_size": "0.1"},
        position={"position_id": "paper-BTC-USDC", "base_size": "0.1"},
    )
    stop = _event(
        "gov-1",
        "governance_status",
        status={"classification": "STOP_NOW", "reason": "fixture_stop"},
        governance=_gov("STOP_NOW"),
    )
    after_stop = _event("entry-after-stop", "c4_entry_order", order={"order_id": "o1", "status": "open", "notional_quote": "5"})

    report = run_paper_lifecycle_simulation([d1, stop, after_stop])

    reasons = [row["reason"] for row in report["rejected_events"]]
    assert "d1_missing_prior_fill_evidence" in reasons
    assert "stop_now_active_blocks_transition" in reasons
    assert "governance_stop_now_active" in report["blockers"]


def test_cli_writes_reports_without_state_mutation(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "reports/d6").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text('{"BTC-USDC": {"position_size_base": "0"}}\n', encoding="utf-8")
    before_open = (tmp_path / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (tmp_path / "state/positions.json").read_text(encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    rc = main(
        [
            "--demo",
            "--json-out",
            "reports/d6/replication-paper-lifecycle-simulator.json",
            "--markdown-out",
            "reports/d6/replication-paper-lifecycle-simulator.md",
        ]
    )

    assert rc == 0
    payload = json.loads((tmp_path / "reports/d6/replication-paper-lifecycle-simulator.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "reports/d6/replication-paper-lifecycle-simulator.md").read_text(encoding="utf-8")
    assert payload["phase"] == PHASE
    assert payload["follower_ready_for_live"] is False
    assert "Replication Paper Lifecycle Simulator" in markdown
    assert render_paper_lifecycle_markdown(payload).startswith("# Replication Paper Lifecycle Simulator")
    assert (tmp_path / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (tmp_path / "state/positions.json").read_text(encoding="utf-8") == before_positions
