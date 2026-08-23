from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.build_btc_usdc_24h_post_run_evidence_pack import (  # noqa: E402
    OK,
    STOP_NOW,
    WATCH,
    _markdown,
    build_post_run_evidence_pack,
    main,
)


START = datetime(2026, 6, 9, 10, 0, tzinfo=timezone.utc)
STOP = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "reports/live").mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "REPLICATION_ENABLED=false",
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
                "ENABLE_LIVE_EXIT_ORDERS=false",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false",
                "AUTONOMOUS_ALLOW_EXITS=false",
                "LEARNING_TO_EXECUTION_ALLOWED=false",
                "PARAMETER_CHANGE_ALLOWED=false",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {}}), encoding="utf-8")
    (tmp_path / "state/positions.json").write_text(json.dumps({"positions": {}}), encoding="utf-8")
    (tmp_path / "logs/loop.log").write_text(
        "\n".join(
            [
                "2026-06-08 09:00:00,000 - INFO - Execution mode=live | tickers=BTC-USDC,ETH-USDC",
                "2026-06-09 10:00:00,000 - INFO - Execution mode=live | tickers=BTC-USDC",
                "2026-06-09 10:01:00,000 - INFO - Ticker BTC-USDC | gate=watch/normal | decision=wait | side=NONE | size_quote=0.0 | confidence=58 | strategy=entry_gate_watch | setup_type=unclear | execution_status=no_trade | executed=False",
                "2026-06-10 10:01:00,000 - INFO - Ticker ETH-USDC | gate=watch/normal | decision=wait | side=NONE | size_quote=0.0 | confidence=58 | strategy=entry_gate_watch | setup_type=unclear | execution_status=no_trade | executed=False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        tmp_path / "logs/cycle_summary.jsonl",
        [
            {"generated_at": "2026-06-08T09:00:00+00:00", "total": 8, "errors": 0, "approve_trade": 0, "executed": 0, "wait": 8},
            {"generated_at": "2026-06-09T10:05:00+00:00", "total": 1, "errors": 0, "approve_trade": 0, "executed": 0, "wait": 1},
        ],
    )
    _write_jsonl(
        tmp_path / "logs/heartbeat_summary.jsonl",
        [{"generated_at": "2026-06-09T11:00:00+00:00", "total": 0, "errors": 0, "heartbeat_ok": 0, "executed": 0}],
    )
    _write_jsonl(
        tmp_path / "logs/phase_c43_lifecycle_service.jsonl",
        [
            {
                "generated_at": "2026-06-09T10:06:00+00:00",
                "status": "completed",
                "summary": {
                    "proposed_actions": 0,
                    "applied_actions": 0,
                    "d2_reports": 0,
                    "d3_previews": 0,
                    "coinbase_call_attempted": False,
                },
            }
        ],
    )
    _write_jsonl(
        tmp_path / "logs/replication_publish.jsonl",
        [{"timestamp": "2026-06-09T10:07:00+00:00", "status": "skipped", "result": {"reason": "replication_disabled"}}],
    )
    _write_jsonl(tmp_path / "logs/replication_outbox.jsonl", [])
    _write_jsonl(tmp_path / "logs/llm_corrupt.jsonl", [])
    _write_jsonl(tmp_path / "logs/llm_provider_errors.jsonl", [])
    return tmp_path


def test_post_run_pack_clean_btc_only_window_is_ok(tmp_path: Path) -> None:
    root = _root(tmp_path)

    report = build_post_run_evidence_pack(
        root=root,
        start_utc=START,
        stop_utc=STOP,
        baseline_open_orders_hash=_sha(root / "state/open_orders.json"),
        baseline_positions_hash=_sha(root / "state/positions.json"),
    )

    assert report["stop_rule_summary"]["status"] == OK
    assert report["run_metadata"]["no_coinbase_call"] is True
    assert report["run_metadata"]["replication_enabled"] is False
    assert report["run_metadata"]["replication_publish_allowed"] is False
    assert report["run_metadata"]["follower_lifecycle_enabled"] is False
    assert report["run_metadata"]["state_write_performed"] is False
    assert report["scope_evidence"]["per_ticker_decision_counts"] == {"BTC-USDC": 1}
    assert report["replication_evidence"]["replication_enabled"] is False
    assert report["replication_evidence"]["replication_publish_allowed"] is False
    assert report["replication_evidence"]["follower_lifecycle_enabled"] is False
    assert report["replication_evidence"]["replication_disabled_reason_seen"] is True


def test_post_run_pack_stops_on_non_btc_ticker_inside_window(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with (root / "logs/loop.log").open("a", encoding="utf-8") as handle:
        handle.write(
            "2026-06-09 12:00:00,000 - INFO - Ticker ETH-USDC | gate=watch/normal | decision=wait | side=NONE | size_quote=0.0 | confidence=58 | strategy=entry_gate_watch | setup_type=unclear | execution_status=no_trade | executed=False\n"
        )

    report = build_post_run_evidence_pack(root=root, start_utc=START, stop_utc=STOP)

    assert report["stop_rule_summary"]["status"] == STOP_NOW
    assert "non_btc_ticker_activity_inside_window" in report["stop_rule_summary"]["reasons"]


def test_post_run_pack_stops_on_executed_order_outside_btc(tmp_path: Path) -> None:
    root = _root(tmp_path)
    order = {
        "client_order_id": "phasec-ETHUSDC-live",
        "ticker": "ETH-USDC",
        "side": "BUY",
        "status": "filled",
        "size_quote": "9.50",
        "updated_at": "2026-06-09T12:00:00+00:00",
    }
    (root / "state/open_orders.json").write_text(json.dumps({"orders": {"eth": order}}), encoding="utf-8")

    report = build_post_run_evidence_pack(root=root, start_utc=START, stop_utc=STOP)

    assert report["stop_rule_summary"]["status"] == STOP_NOW
    assert "executed_or_submitted_non_btc_order_inside_window" in report["stop_rule_summary"]["reasons"]


def test_post_run_pack_stops_on_baseline_hash_mismatch_and_does_not_write_state(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_post_run_evidence_pack(
        root=root,
        start_utc=START,
        stop_utc=STOP,
        baseline_open_orders_hash="not-current",
        baseline_positions_hash="not-current",
    )

    assert report["stop_rule_summary"]["status"] == STOP_NOW
    assert "state_hash_drift_open_orders" in report["stop_rule_summary"]["reasons"]
    assert "state_hash_drift_positions" in report["stop_rule_summary"]["reasons"]
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions


def test_post_run_pack_watches_single_llm_and_provider_error(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_jsonl(root / "logs/llm_corrupt.jsonl", [{"generated_at": "2026-06-09T12:00:00+00:00", "ticker": "BTC-USDC"}])
    _write_jsonl(root / "logs/llm_provider_errors.jsonl", [{"generated_at": "2026-06-09T12:01:00+00:00", "provider": "openai"}])

    report = build_post_run_evidence_pack(root=root, start_utc=START, stop_utc=STOP)

    assert report["stop_rule_summary"]["status"] == WATCH
    assert "llm_corrupt_seen_inside_window" in report["stop_rule_summary"]["reasons"]
    assert "provider_error_seen_inside_window" in report["stop_rule_summary"]["reasons"]


def test_post_run_pack_writes_json_and_markdown_with_required_sections(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")
    monkeypatch.chdir(root)

    rc = main(
        [
            "--start-utc",
            "2026-06-09T10:00:00+00:00",
            "--stop-utc",
            "2026-06-10T10:00:00+00:00",
            "--json-out",
            "reports/live/evidence.json",
            "--markdown-out",
            "reports/live/evidence.md",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/live/evidence.json").read_text(encoding="utf-8"))
    markdown = (root / "reports/live/evidence.md").read_text(encoding="utf-8")
    assert payload["phase"] == "btc_usdc_24h_post_run_evidence_pack_v1"
    for section in (
        "## Run Metadata",
        "## Scope Evidence",
        "## Cycle Evidence",
        "## Heartbeat Evidence",
        "## Order And Lifecycle Evidence",
        "## LLM And Provider Evidence",
        "## Replication Evidence",
        "## State Hash Evidence",
        "## Conclusion",
    ):
        assert section in markdown
    assert "replication_enabled: `False`" in markdown
    assert "replication_publish_allowed: `False`" in markdown
    assert "follower_lifecycle_enabled: `False`" in markdown
    assert "replication_disabled_reason_seen: `True`" in markdown
    assert "BTC-USDC 24h Post-Run Evidence Pack" in _markdown(payload)
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
