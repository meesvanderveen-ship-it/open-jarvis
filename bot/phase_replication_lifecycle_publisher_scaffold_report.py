from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_replication_lifecycle_golden_payloads import build_positive_golden_sequence
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION
from replication.config import ReplicationConfig
from replication.lifecycle_publisher import (
    LIFECYCLE_ENDPOINT,
    LIFECYCLE_PHASE,
    LifecyclePublishConfig,
    LifecycleReplicaPublisher,
    publish_lifecycle_events_disabled_scaffold,
)


PHASE = "replication_lifecycle_publisher_scaffold_report_v1"


def _sha256(root: Path, rel: str) -> str:
    path = root / rel
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _enabled_fixture_config() -> LifecyclePublishConfig:
    return LifecyclePublishConfig(
        replication_config=ReplicationConfig(
            enabled=True,
            replica_url="https://replica.example.invalid",
            shared_hmac_secret="fixture-secret",
            source_bot_name="server1-master",
            timeout_seconds=15,
            verify_tls=True,
        ),
        lifecycle_enabled=False,
        allow_http_transport=False,
    )


def build_replication_lifecycle_publisher_scaffold_report(*, root: Path | str = ".") -> Dict[str, Any]:
    repo = Path(root)
    events = build_positive_golden_sequence()
    disabled_result = publish_lifecycle_events_disabled_scaffold(events)

    enabled_config = _enabled_fixture_config()
    enabled_disabled_lifecycle_result = publish_lifecycle_events_disabled_scaffold(events, config=enabled_config)
    request_sample = LifecycleReplicaPublisher(config=enabled_config).build_request(events[0])

    no_http_passed = (
        disabled_result.get("http_attempted") is False
        and enabled_disabled_lifecycle_result.get("http_attempted") is False
        and disabled_result.get("all_skipped") is True
        and enabled_disabled_lifecycle_result.get("all_skipped") is True
    )
    schema_request_passed = (
        request_sample.get("ok") is True
        and request_sample.get("endpoint") == "https://replica.example.invalid" + LIFECYCLE_ENDPOINT
        and bool((request_sample.get("headers") or {}).get("x-replica-signature"))
        and request_sample.get("body", {}).get("schema_version") == SCHEMA_VERSION
    )
    scaffold_validation_passed = bool(no_http_passed and schema_request_passed)

    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "publisher_phase": LIFECYCLE_PHASE,
        "report_mode": "read_only_replication_lifecycle_publisher_scaffold",
        "schema_version": SCHEMA_VERSION,
        "no_coinbase_call": True,
        "http_replication_call_attempted": False,
        "state_write_performed": False,
        "replication_enabled_by_report": False,
        "follower_live_enabled": False,
        "lifecycle_publisher_scaffold_ready": scaffold_validation_passed,
        "lifecycle_http_transport_enabled": False,
        "lifecycle_runtime_integrated": False,
        "lifecycle_parity_ready": False,
        "follower_ready_for_live": False,
        "master_live_exit_ready": False,
        "all_ticker_ready": False,
        "learning_to_execution_ready": False,
        "disabled_config_result": disabled_result,
        "enabled_replication_but_lifecycle_disabled_result": enabled_disabled_lifecycle_result,
        "request_sample": {
            "ok": request_sample.get("ok"),
            "event_id": request_sample.get("event_id"),
            "event_type": request_sample.get("event_type"),
            "endpoint": request_sample.get("endpoint"),
            "body_sha256": request_sample.get("body_sha256"),
            "signature_present": bool((request_sample.get("headers") or {}).get("x-replica-signature")),
            "schema_version": (request_sample.get("body") or {}).get("schema_version"),
            "live_order_action": (request_sample.get("body") or {}).get("live_order_action"),
            "state_mutation": (request_sample.get("body") or {}).get("state_mutation"),
        },
        "validation": {
            "golden_event_count": len(events),
            "no_http_passed": no_http_passed,
            "schema_request_passed": schema_request_passed,
            "scaffold_validation_passed": scaffold_validation_passed,
            "disabled_reasons": sorted({str(row.get("reason")) for row in disabled_result.get("results", [])}),
            "enabled_but_lifecycle_disabled_reasons": sorted(
                {str(row.get("reason")) for row in enabled_disabled_lifecycle_result.get("results", [])}
            ),
        },
        "remaining_before_runtime_integration": [
            "operator-approved lifecycle publisher callsite design",
            "replication disabled/no-http tests at runtime callsite",
            "explicit endpoint/HMAC receiver contract",
            "follower receiver/API audit",
            "paper-to-live ACK model for follower BUY and SELL separately",
        ],
        "recommended_next_sprint": {
            "route": "exit_workflow_readiness_d2_d3_d4_d5_hardening",
            "why": "Replication lifecycle publishing is now scaffolded fail-closed; next highest core workflow gap is exit readiness/no-oversell/reservation/D4-D5 evidence hardening before any live exit or follower SELL work.",
        },
        "state_hashes": {
            "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
            "state/positions.json": _sha256(repo, "state/positions.json"),
        },
        **d6_metric_safety_flags(),
    }


def render_replication_lifecycle_publisher_scaffold_markdown(report: Dict[str, Any]) -> str:
    validation = report.get("validation") or {}
    lines = [
        "# Replication Lifecycle Publisher Scaffold",
        "",
        "Read-only scaffold report. It does not enable replication, send HTTP, call Coinbase, place orders, integrate runtime callsites, or mutate trading state.",
        "",
        "## Validation",
        f"- lifecycle_publisher_scaffold_ready: `{report.get('lifecycle_publisher_scaffold_ready')}`",
        f"- lifecycle_http_transport_enabled: `{report.get('lifecycle_http_transport_enabled')}`",
        f"- lifecycle_runtime_integrated: `{report.get('lifecycle_runtime_integrated')}`",
        f"- lifecycle_parity_ready: `{report.get('lifecycle_parity_ready')}`",
        f"- follower_ready_for_live: `{report.get('follower_ready_for_live')}`",
        f"- no_http_passed: `{validation.get('no_http_passed')}`",
        f"- schema_request_passed: `{validation.get('schema_request_passed')}`",
        f"- scaffold_validation_passed: `{validation.get('scaffold_validation_passed')}`",
        f"- disabled_reasons: `{', '.join(validation.get('disabled_reasons') or [])}`",
        f"- enabled_but_lifecycle_disabled_reasons: `{', '.join(validation.get('enabled_but_lifecycle_disabled_reasons') or [])}`",
        "",
        "## Request Sample",
    ]
    for key, value in (report.get("request_sample") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Remaining Before Runtime Integration"])
    for item in report.get("remaining_before_runtime_integration") or []:
        lines.append(f"- {item}")
    next_sprint = report.get("recommended_next_sprint") or {}
    lines.extend([
        "",
        "## Recommended Next Sprint",
        f"- route: `{next_sprint.get('route')}`",
        f"- why: {next_sprint.get('why')}",
        "",
        "## State Hashes",
    ])
    for key, value in (report.get("state_hashes") or {}).items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "build_replication_lifecycle_publisher_scaffold_report",
    "render_replication_lifecycle_publisher_scaffold_markdown",
]
