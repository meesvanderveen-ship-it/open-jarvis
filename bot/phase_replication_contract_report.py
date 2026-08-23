from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "replication_follower_contract_report_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "learning_to_execution_enabled": False,
        "follower_live_enabled": False,
        "replication_enabled_by_report": False,
    }


def _read_text(root: Path, rel: str, max_chars: int = 750_000) -> str:
    path = root / rel
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


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


def _iter_jsonl(path: Path, limit: int = 500) -> List[Dict[str, Any]]:
    try:
        if not path.exists() or not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _env_value(root: Path, name: str) -> str:
    env_text = _read_text(root, ".env", max_chars=200_000)
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(env_text)
    if match:
        return match.group(1).strip().strip("'\"")
    return os.environ.get(name, "").strip()


def _env_bool(root: Path, name: str, default: bool = False) -> bool:
    raw = _env_value(root, name)
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _contains(root: Path, rel: str, needle: str) -> bool:
    return needle in _read_text(root, rel)


def _extract_envelope_fields(root: Path) -> List[str]:
    text = _read_text(root, "replication/models.py")
    fields: List[str] = []
    in_class = False
    for line in text.splitlines():
        if line.startswith("class ReplicationEnvelope"):
            in_class = True
            continue
        if in_class and line.startswith("    def "):
            break
        if in_class:
            match = re.match(r"\s{4}([a-zA-Z_][a-zA-Z0-9_]*)\s*:", line)
            if match:
                fields.append(match.group(1))
    return fields


def _log_evidence(root: Path) -> Dict[str, Any]:
    outbox_rows = _iter_jsonl(root / "logs/replication_outbox.jsonl")
    publish_rows = _iter_jsonl(root / "logs/replication_publish.jsonl")
    result_reasons = Counter()
    outbox_status = Counter()
    sent_or_enabled = 0
    skipped_disabled = 0
    sample_payload_keys: List[str] = []
    for row in outbox_rows:
        outbox_status[str(row.get("status") or "unknown")] += 1
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        reason = str(result.get("reason") or "")
        if reason:
            result_reasons[reason] += 1
        if reason == "replication_disabled" or str(row.get("status")) == "skipped":
            skipped_disabled += 1
        if str(row.get("status")) in {"sent", "http_error"}:
            sent_or_enabled += 1
        payload = row.get("payload")
        if isinstance(payload, dict) and not sample_payload_keys:
            sample_payload_keys = sorted(payload.keys())
    for row in publish_rows:
        result = row.get("publish_result") if isinstance(row.get("publish_result"), dict) else {}
        if result.get("ok") is True or result.get("status_code"):
            sent_or_enabled += 1
    return {
        "logs_present": {
            "logs/replication_outbox.jsonl": _path_exists(root, "logs/replication_outbox.jsonl"),
            "logs/replication_publish.jsonl": _path_exists(root, "logs/replication_publish.jsonl"),
        },
        "outbox_rows_sampled": len(outbox_rows),
        "publish_rows_sampled": len(publish_rows),
        "outbox_status_counts": dict(outbox_status),
        "result_reason_counts": dict(result_reasons),
        "skipped_disabled_count": skipped_disabled,
        "sent_or_enabled_evidence_count": sent_or_enabled,
        "sample_payload_keys": sample_payload_keys,
        "recent_publish_sample": publish_rows[-3:],
    }


def _publisher_summary(root: Path) -> Dict[str, Any]:
    envelope_fields = _extract_envelope_fields(root)
    publisher_text = _read_text(root, "replication/publisher.py")
    runner_text = _read_text(root, "run_trader_loop.py")
    hmac_present = "hmac.new" in publisher_text and "x-replica-signature" in publisher_text
    endpoint_match = re.search(r'url\s*=\s*f"\{self\.config\.replica_url\}([^"]+)"', publisher_text)
    return {
        "files_inspected": [
            rel for rel in (
                "replication/models.py",
                "replication/publisher.py",
                "replication/config.py",
                "run_trader_loop.py",
                "logs/replication_outbox.jsonl",
                "logs/replication_publish.jsonl",
            )
            if _path_exists(root, rel)
        ],
        "payload_model": "ReplicationEnvelope" if envelope_fields else "missing",
        "payload_fields": envelope_fields,
        "schema_version_field_present": "schema_version" in envelope_fields,
        "idempotency_fields": [field for field in ("event_id", "timestamp", "source_bot", "ticker") if field in envelope_fields],
        "auth_fields": {
            "hmac_sha256_present": hmac_present,
            "header": "x-replica-signature" if "x-replica-signature" in publisher_text else "",
            "shared_secret_env": "REPLICA_SHARED_HMAC_SECRET" if "REPLICA_SHARED_HMAC_SECRET" in _read_text(root, "replication/config.py") else "",
        },
        "endpoint": endpoint_match.group(1) if endpoint_match else "/api/replica/decision" if "/api/replica/decision" in publisher_text else "",
        "master_publish_calls": {
            "full_cycle": "_replicate_full_cycle_results" in runner_text,
            "heartbeat": "_replicate_heartbeat_results" in runner_text,
            "helper": "publish_decision_best_effort" in runner_text,
        },
        "current_flags": {
            "REPLICATION_ENABLED": _env_value(root, "REPLICATION_ENABLED") or "false",
            "REPLICA_URL_present": bool(_env_value(root, "REPLICA_URL")),
            "REPLICA_SHARED_HMAC_SECRET_present": bool(_env_value(root, "REPLICA_SHARED_HMAC_SECRET")),
            "REPLICATION_SOURCE_BOT": _env_value(root, "REPLICATION_SOURCE_BOT") or "server1-master",
        },
        "local_log_evidence": _log_evidence(root),
    }


def _follower_visibility(root: Path) -> Dict[str, Any]:
    receiver_patterns = [
        "api/replica/decision",
        "replica/decision",
        "FastAPI",
        "Flask",
        "verify_signature",
        "x-replica-signature",
    ]
    rels = [str(path.relative_to(root)) for path in (root / "replication").glob("*.py")] if (root / "replication").exists() else []
    receiver_hits: Dict[str, List[str]] = {}
    for rel in rels:
        text = _read_text(root, rel)
        hits = [pattern for pattern in receiver_patterns if pattern in text]
        if hits:
            receiver_hits[rel] = hits
    # The publisher necessarily contains the endpoint string; receiver visibility
    # requires non-publisher server/API code, which is not present in this repo.
    server_receiver_files = {
        rel: hits for rel, hits in receiver_hits.items()
        if rel not in {"replication/publisher.py"}
    }
    status = "present" if server_receiver_files else "missing_in_repo"
    return {
        "status": status,
        "receiver_files_found": server_receiver_files,
        "note": "Follower receiver/API implementation is not present in this repository." if status == "missing_in_repo" else "",
    }


def _gap_row(stage: str, classification: str, current: str, target: str, policy: str, tests: List[str]) -> Dict[str, Any]:
    return {
        "workflow_stage": stage,
        "classification": classification,
        "current_master_payload": current,
        "target_contract": target,
        "follower_policy": policy,
        "recommended_tests": tests,
    }


def _gap_matrix() -> List[Dict[str, Any]]:
    return [
        _gap_row(
            "master_decision",
            "published_now",
            "ReplicationEnvelope carries decision, ticker, side, strategy/setup, confidence, requested sizes, reasons, analysis, entry_gate, risk_context, position_context and metadata.",
            "Add explicit schema_version and follower_mode fields before any live follower use.",
            "Follower may observe/paper-simulate decisions only; live execution requires its own ACK and caps.",
            ["required envelope fields", "schema version forward compatibility", "idempotent event_id handling"],
        ),
        _gap_row(
            "C4_submitted_open_rejected_cancelled_filled_partial",
            "should_publish_later",
            "C4 lifecycle evidence is not modeled as first-class replication event types.",
            "Define lifecycle_event_type, order ids, terminal status, fill sizes/fees, and source evidence hashes.",
            "Follower observes/reconciles only; no order submit/cancel/replace from lifecycle events by default.",
            ["lifecycle event cannot trigger follower live action", "partial fill payload requires exact sizes/fees", "unknown lifecycle status safe"],
        ),
        _gap_row(
            "D1_fill_to_position",
            "requires_separate_follower_ACK",
            "Fill-to-position remains master-local C4.5/D1 logic, not a follower contract.",
            "Define position-open evidence payload only after C4 fill contract exists.",
            "Follower must not create live position state from master fill without its own evidence and ACK.",
            ["fill apply event remains observe-only", "state mutation blocked without follower ACK"],
        ),
        _gap_row(
            "D2_position_plan",
            "should_publish_later",
            "D2 plan can appear in master lifecycle apply/preview contexts but is not a replication contract object.",
            "Publish plan fingerprint, position id, exits as preview-only advisory metadata.",
            "Follower treats D2 as paper-only advisory; own caps/product rules must be recalculated.",
            ["plan fingerprint required", "follower recalculates caps", "D2 does not imply D3 live exit"],
        ),
        _gap_row(
            "D3_preview_exit_intent",
            "must_remain_disabled",
            "D3 preview/exit submit is explicitly isolated from followers in current lifecycle guards.",
            "Only publish preview intent after separate design; never publish as live SELL permission.",
            "Follower ignores D3/live exit events unless explicitly enabled with separate ACK.",
            ["D3 preview is non-live", "live exit event rejected by default", "replication enabled blocks D3 governance"],
        ),
        _gap_row(
            "D4_trailing_cancel_replace",
            "must_remain_master_only",
            "D4 cancel/replace is preview/ACK-gated and not part of replication envelope.",
            "If ever published, require cancel-first, order-id, reservation and explicit follower ACK fields.",
            "Follower must not cancel/replace from master events by default.",
            ["cancel/replace event observe-only", "requires order-id/action ACK"],
        ),
        _gap_row(
            "D5_execution_metrics",
            "should_publish_later",
            "D5 metrics are local report scaffolds, not replication payloads.",
            "Publish read-only execution evidence summaries and hashes for follower audit parity.",
            "Follower may consume metrics for human review only, not learning-to-execution.",
            ["metrics are read-only", "no learning-to-execution bridge"],
        ),
        _gap_row(
            "D6_research_signals",
            "must_remain_disabled",
            "D6 research/backlearning remains report-only and outside replication execution.",
            "No research signal should become follower trade permission.",
            "Follower ignores D6 research signals for live action.",
            ["D6 payload cannot set live recommendation", "parameter mutation blocked"],
        ),
        _gap_row(
            "STOP_WATCH_OK_evidence",
            "should_publish_later",
            "Monitor/post-run classifications exist locally but are not in replication envelope.",
            "Publish status classifications as read-only safety telemetry with evidence hashes.",
            "Follower treats STOP_NOW as halt/review signal, not repair/apply authorization.",
            ["STOP_NOW cannot trigger repair", "WATCH requires human review"],
        ),
    ]


def _contract_tests(root: Path) -> Dict[str, Any]:
    present = []
    for rel in (
        "tests/test_replication_config_env_skip.py",
        "tests/test_phase_c43_one_entry_smoke_test.py",
        "tests/test_phase_d3_cancel_replace_governance.py",
        "tests/test_phase_d3_controlled_exit_pilot.py",
    ):
        if _path_exists(root, rel):
            present.append(rel)
    return {
        "current_tests_present": present,
        "missing_tests": [
            "ReplicationEnvelope required-fields and schema-version compatibility test",
            "publish_decision_best_effort idempotency/event_id preservation test",
            "HMAC signing and receiver verification contract test",
            "replication disabled logs skipped/no HTTP test",
            "unknown/new fields are safely ignored by follower test",
            "lifecycle event does not cause follower live action by default test",
            "follower paper-only boundaries and independent caps/product-rules test",
        ],
        "recommended_next_tests": [
            "Add schema fixture golden JSON for decision envelope v1",
            "Add follower receiver/API audit once receiver code is available",
            "Add lifecycle-observe-only fixtures for C4/D1/D2/D3 events before enabling any follower",
        ],
    }


def _status(summary: Dict[str, Any]) -> Dict[str, Any]:
    flags = summary["current_flags"]
    logs = summary["local_log_evidence"]
    if str(flags.get("REPLICATION_ENABLED", "")).lower() == "true" or logs.get("sent_or_enabled_evidence_count", 0) > 0:
        return {
            "status": "STOP_NOW",
            "reasons": ["replication_enabled_or_sent_evidence_present"],
            "operator_next_step": "Disable/review replication before any live or follower work; no follower action without exact ACK.",
        }
    return {
        "status": "WATCH",
        "reasons": [
            "master_decision_publisher_exists",
            "replication_disabled_currently_safe",
            "lifecycle_contract_parity_incomplete",
            "follower_receiver_missing_in_repo",
        ],
        "operator_next_step": "Keep replication disabled; use this contract for follower/API audit and lifecycle-observe-only tests next.",
    }


def build_replication_contract_report(*, root: Path | str = ".") -> Dict[str, Any]:
    repo = Path(root)
    publisher = _publisher_summary(repo)
    follower = _follower_visibility(repo)
    status = _status(publisher)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_mode": "read_only_replication_follower_contract",
        "contract_status": {
            "status": status["status"],
            "current_contract_shape": "decision_only_master_publisher",
            "follower_visibility": follower["status"],
            "schema_version": "missing",
            "idempotency_fields": publisher["idempotency_fields"],
            "hmac_auth": publisher["auth_fields"],
            "reasons": status["reasons"],
            "operator_next_step": status["operator_next_step"],
        },
        "current_master_publisher_summary": publisher,
        "follower_receiver_visibility": follower,
        "gap_matrix": _gap_matrix(),
        "follower_policy_recommendation": {
            "follower_live_remains_disabled_out_of_scope": True,
            "paper_only_unless_separately_approved": True,
            "do_not_execute_d3_or_live_exit_events_by_default": True,
            "follower_must_apply_own_product_rules_balances_caps_and_drift_checks": True,
            "lifecycle_events_are_observe_reconcile_only_unless_explicitly_enabled": True,
            "partial_fills_or_drift_require_stop_watch_review": True,
            "follower_requires_own_live_ACK": True,
            "unknown_fields_must_be_ignored_or_fail_closed": True,
        },
        "required_contract_tests": _contract_tests(repo),
        "state_hashes": {
            "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
            "state/positions.json": _sha256(repo, "state/positions.json"),
        },
        "recommended_next_sprint": {
            "route": "follower_receiver_api_audit",
            "why": "Master publisher is decision-only and follower receiver/API is not visible in this repo; receiver behavior must be audited before hardening lifecycle parity.",
        },
        **_safety_flags(),
    }


def render_replication_contract_markdown(report: Dict[str, Any]) -> str:
    status = report.get("contract_status") or {}
    publisher = report.get("current_master_publisher_summary") or {}
    lines = [
        "# Replication/Follower Contract Report",
        "",
        "Read-only contract artifact. No live replication, no follower live action, no Coinbase calls and no trading-state writes.",
        "",
        "## Summary",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{status.get('status')}`",
        f"- current_contract_shape: `{status.get('current_contract_shape')}`",
        f"- follower_visibility: `{status.get('follower_visibility')}`",
        f"- schema_version: `{status.get('schema_version')}`",
        f"- reasons: `{', '.join(status.get('reasons') or [])}`",
        f"- operator_next_step: {status.get('operator_next_step')}",
        "",
        "## Master Publisher",
        f"- files_inspected: `{', '.join(publisher.get('files_inspected') or [])}`",
        f"- payload_model: `{publisher.get('payload_model')}`",
        f"- payload_fields: `{', '.join(publisher.get('payload_fields') or [])}`",
        f"- idempotency_fields: `{', '.join(publisher.get('idempotency_fields') or [])}`",
        f"- hmac_sha256_present: `{((publisher.get('auth_fields') or {}).get('hmac_sha256_present'))}`",
        f"- endpoint: `{publisher.get('endpoint')}`",
        f"- REPLICATION_ENABLED: `{((publisher.get('current_flags') or {}).get('REPLICATION_ENABLED'))}`",
        "",
        "## Gap Matrix",
    ]
    for row in report.get("gap_matrix") or []:
        lines.extend([
            "",
            f"### {row.get('workflow_stage')}",
            f"- classification: `{row.get('classification')}`",
            f"- current_master_payload: {row.get('current_master_payload')}",
            f"- target_contract: {row.get('target_contract')}",
            f"- follower_policy: {row.get('follower_policy')}",
        ])
    policy = report.get("follower_policy_recommendation") or {}
    lines.extend(["", "## Follower Policy"])
    for key, value in policy.items():
        lines.append(f"- {key}: `{value}`")
    tests = report.get("required_contract_tests") or {}
    lines.extend(["", "## Required Tests"])
    lines.append(f"- current_tests_present: `{', '.join(tests.get('current_tests_present') or [])}`")
    lines.append(f"- missing_tests: `{'; '.join(tests.get('missing_tests') or [])}`")
    lines.append(f"- recommended_next_tests: `{'; '.join(tests.get('recommended_next_tests') or [])}`")
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


__all__ = ["PHASE", "build_replication_contract_report", "render_replication_contract_markdown"]
