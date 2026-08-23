from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_replication_contract_report import (  # noqa: E402
    PHASE,
    build_replication_contract_report,
    render_replication_contract_markdown,
)
from tools.build_replication_contract_report import main  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    _write(path, "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")


def _root(tmp_path: Path, *, replication_enabled: bool = False, sent: bool = False) -> Path:
    _write(
        tmp_path / ".env",
        "\n".join(
            [
                f"REPLICATION_ENABLED={'true' if replication_enabled else 'false'}",
                "REPLICA_URL=https://example.invalid",
                "REPLICA_SHARED_HMAC_SECRET=test-secret",
                "REPLICATION_SOURCE_BOT=SERVER1-MASTER",
            ]
        ),
    )
    _write(
        tmp_path / "replication/models.py",
        """
from dataclasses import dataclass, field
@dataclass
class ReplicationEnvelope:
    event_id: str
    timestamp: str
    source_bot: str
    ticker: str
    decision: str
    side: str
    strategy: str | None = None
    setup_type: str | None = None
    confidence: int = 0
    requested_size_quote: float = 0.0
    requested_size_base: float = 0.0
    reason_summary: list[str] = field(default_factory=list)
    must_reject_if: list[str] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    entry_gate: dict = field(default_factory=dict)
    risk_context: dict = field(default_factory=dict)
    position_context: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
""".strip(),
    )
    _write(
        tmp_path / "replication/publisher.py",
        "hmac.new(b'', b'', hashlib.sha256)\nheaders={'x-replica-signature': 'sig'}\nurl = f\"{self.config.replica_url}/api/replica/decision\"\npublish_decision_best_effort\n",
    )
    _write(tmp_path / "replication/config.py", "REPLICA_SHARED_HMAC_SECRET\nREPLICATION_ENABLED\n")
    _write(
        tmp_path / "run_trader_loop.py",
        "_replicate_full_cycle_results\n_replicate_heartbeat_results\npublish_decision_best_effort\n",
    )
    _write(tmp_path / "state/open_orders.json", '{"orders": {}}\n')
    _write(tmp_path / "state/positions.json", '{"BTC-USDC": {"position_size_base": "0"}}\n')
    _jsonl(
        tmp_path / "logs/replication_outbox.jsonl",
        [
            {
                "timestamp": "2026-06-09T00:00:00+00:00",
                "status": "sent" if sent else "skipped",
                "payload": {"event_id": "evt-1", "ticker": "BTC-USDC", "decision": "wait"},
                "result": {"ok": bool(sent), "reason": "" if sent else "replication_disabled"},
            }
        ],
    )
    _jsonl(
        tmp_path / "logs/replication_publish.jsonl",
        [
            {
                "generated_at": "2026-06-09T00:00:00+00:00",
                "cycle_type": "full",
                "ticker": "BTC-USDC",
                "decision": "wait",
                "publish_result": {"ok": bool(sent), "skipped": not sent, "reason": "" if sent else "replication_disabled"},
            }
        ],
    )
    (tmp_path / "reports/d6").mkdir(parents=True)
    return tmp_path


def test_replication_contract_report_classifies_disabled_decision_publisher_as_watch(tmp_path: Path) -> None:
    report = build_replication_contract_report(root=_root(tmp_path))

    assert report["phase"] == PHASE
    assert report["contract_status"]["status"] == "WATCH"
    assert report["contract_status"]["current_contract_shape"] == "decision_only_master_publisher"
    assert report["follower_receiver_visibility"]["status"] == "missing_in_repo"
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert "event_id" in report["current_master_publisher_summary"]["payload_fields"]
    assert report["current_master_publisher_summary"]["schema_version_field_present"] is False


def test_replication_contract_report_stop_now_when_enabled_or_sent(tmp_path: Path) -> None:
    enabled = build_replication_contract_report(root=_root(tmp_path / "enabled", replication_enabled=True))
    sent = build_replication_contract_report(root=_root(tmp_path / "sent", sent=True))

    assert enabled["contract_status"]["status"] == "STOP_NOW"
    assert sent["contract_status"]["status"] == "STOP_NOW"


def test_gap_matrix_and_policy_make_lifecycle_observe_only(tmp_path: Path) -> None:
    report = build_replication_contract_report(root=_root(tmp_path))
    rows = {row["workflow_stage"]: row for row in report["gap_matrix"]}
    policy = report["follower_policy_recommendation"]

    assert rows["master_decision"]["classification"] == "published_now"
    assert rows["C4_submitted_open_rejected_cancelled_filled_partial"]["classification"] == "should_publish_later"
    assert rows["D3_preview_exit_intent"]["classification"] == "must_remain_disabled"
    assert policy["paper_only_unless_separately_approved"] is True
    assert policy["do_not_execute_d3_or_live_exit_events_by_default"] is True
    assert policy["follower_must_apply_own_product_rules_balances_caps_and_drift_checks"] is True


def test_markdown_and_cli_write_reports_without_state_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")
    report = build_replication_contract_report(root=root)
    markdown = render_replication_contract_markdown(report)

    assert "# Replication/Follower Contract Report" in markdown
    assert "Follower Policy" in markdown
    assert "D3_preview_exit_intent" in markdown

    monkeypatch.chdir(root)
    rc = main(
        [
            "--json-out",
            "reports/d6/replication-contract-report.json",
            "--markdown-out",
            "reports/d6/replication-contract-report.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/replication-contract-report.json").read_text(encoding="utf-8"))
    assert payload["phase"] == PHASE
    assert "Replication/Follower Contract Report" in (root / "reports/d6/replication-contract-report.md").read_text(encoding="utf-8")
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
