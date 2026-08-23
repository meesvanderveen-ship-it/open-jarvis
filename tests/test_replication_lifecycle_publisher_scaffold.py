from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_replication_lifecycle_golden_payloads import build_positive_golden_sequence  # noqa: E402
from bot.phase_replication_lifecycle_publisher_scaffold_report import (  # noqa: E402
    PHASE,
    build_replication_lifecycle_publisher_scaffold_report,
    render_replication_lifecycle_publisher_scaffold_markdown,
)
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION  # noqa: E402
from replication.config import ReplicationConfig  # noqa: E402
from replication.lifecycle_publisher import (  # noqa: E402
    LIFECYCLE_ENDPOINT,
    LifecyclePublishConfig,
    LifecycleReplicaPublisher,
    publish_lifecycle_events_disabled_scaffold,
)
from tools.build_replication_lifecycle_publisher_scaffold_report import main  # noqa: E402


def _root(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "reports/d6").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text('{"BTC-USDC": {"position_size_base": "0"}}\n', encoding="utf-8")
    return tmp_path


def _enabled_config(*, lifecycle_enabled: bool = False) -> LifecyclePublishConfig:
    return LifecyclePublishConfig(
        replication_config=ReplicationConfig(
            enabled=True,
            replica_url="https://replica.example.invalid",
            shared_hmac_secret="fixture-secret",
            source_bot_name="server1-master",
            timeout_seconds=15,
            verify_tls=True,
        ),
        lifecycle_enabled=lifecycle_enabled,
        allow_http_transport=False,
    )


def test_disabled_lifecycle_scaffold_skips_all_golden_events_without_http() -> None:
    result = publish_lifecycle_events_disabled_scaffold(build_positive_golden_sequence())

    assert result["all_skipped"] is True
    assert result["http_attempted"] is False
    assert result["state_write_performed"] is False
    assert result["coinbase_call_attempted"] is False
    assert {row["reason"] for row in result["results"]} == {"replication_disabled"}


def test_enabled_replication_still_blocks_lifecycle_when_lifecycle_flag_disabled() -> None:
    publisher = LifecycleReplicaPublisher(config=_enabled_config(lifecycle_enabled=False))
    event = build_positive_golden_sequence()[0]

    result = publisher.publish_lifecycle_best_effort(event)

    assert result["ok"] is False
    assert result["skipped"] is True
    assert result["reason"] == "lifecycle_replication_disabled"
    assert result["http_attempted"] is False
    assert result["request"]["endpoint"] == "https://replica.example.invalid" + LIFECYCLE_ENDPOINT
    assert result["request"]["signature_present"] is True


def test_lifecycle_enabled_scaffold_still_does_not_send_http() -> None:
    publisher = LifecycleReplicaPublisher(config=_enabled_config(lifecycle_enabled=True))
    event = build_positive_golden_sequence()[0]

    result = publisher.publish_lifecycle_best_effort(event)

    assert result["ok"] is False
    assert result["skipped"] is True
    assert result["reason"] == "lifecycle_http_disabled"
    assert result["http_attempted"] is False


def test_build_request_is_canonical_signed_schema_v1() -> None:
    publisher = LifecycleReplicaPublisher(config=_enabled_config(lifecycle_enabled=False))
    event = build_positive_golden_sequence()[1]

    request = publisher.build_request(event)

    assert request["ok"] is True
    assert request["schema_version"] == SCHEMA_VERSION
    assert request["endpoint"] == "https://replica.example.invalid" + LIFECYCLE_ENDPOINT
    assert request["headers"]["x-replica-signature"]
    assert request["body"]["event_id"] == event["event_id"]
    assert request["body"]["live_order_action"] is False
    assert request["body"]["state_mutation"] is False


def test_schema_invalid_event_fails_without_http() -> None:
    publisher = LifecycleReplicaPublisher(config=_enabled_config(lifecycle_enabled=True))
    event = dict(build_positive_golden_sequence()[0])
    event["schema_version"] = "future.schema"

    result = publisher.publish_lifecycle_best_effort(event)

    assert result["ok"] is False
    assert result["skipped"] is True
    assert result["reason"] == "schema_validation_failed"
    assert result["http_attempted"] is False
    assert "schema_version_mismatch" in result["errors"]


def test_report_and_cli_write_artifacts_without_state_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_replication_lifecycle_publisher_scaffold_report(root=root)
    markdown = render_replication_lifecycle_publisher_scaffold_markdown(report)

    assert report["phase"] == PHASE
    assert report["lifecycle_publisher_scaffold_ready"] is True
    assert report["http_replication_call_attempted"] is False
    assert report["lifecycle_http_transport_enabled"] is False
    assert report["follower_ready_for_live"] is False
    assert "Replication Lifecycle Publisher Scaffold" in markdown

    monkeypatch.chdir(root)
    rc = main(
        [
            "--json-out",
            "reports/d6/replication-lifecycle-publisher-scaffold.json",
            "--markdown-out",
            "reports/d6/replication-lifecycle-publisher-scaffold.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/replication-lifecycle-publisher-scaffold.json").read_text(encoding="utf-8"))
    assert payload["phase"] == PHASE
    assert payload["validation"]["scaffold_validation_passed"] is True
    assert "Replication Lifecycle Publisher Scaffold" in (
        root / "reports/d6/replication-lifecycle-publisher-scaffold.md"
    ).read_text(encoding="utf-8")
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
