from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests import exceptions as requests_exceptions

from replication.config import ReplicationConfig, get_bool_env
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION, validate_lifecycle_event_v1


LIFECYCLE_ENDPOINT = "/api/replica/lifecycle"
LIFECYCLE_PHASE = "replication_lifecycle_publisher_v1"
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


@dataclass
class LifecyclePublishConfig:
    replication_config: ReplicationConfig
    lifecycle_enabled: bool = False
    allow_http_transport: bool = False

    @classmethod
    def from_env(cls) -> "LifecyclePublishConfig":
        return cls(
            replication_config=ReplicationConfig.from_env(),
            lifecycle_enabled=get_bool_env("REPLICATION_LIFECYCLE_ENABLED", False),
            allow_http_transport=get_bool_env("REPLICATION_LIFECYCLE_HTTP_ENABLED", False),
        )

    @classmethod
    def disabled(cls, *, source_bot_name: str = "server1-master", shared_hmac_secret: str = "") -> "LifecyclePublishConfig":
        return cls(
            replication_config=ReplicationConfig(
                enabled=False,
                replica_url="",
                shared_hmac_secret=shared_hmac_secret,
                source_bot_name=source_bot_name,
                timeout_seconds=5,
                verify_tls=True,
            ),
            lifecycle_enabled=False,
            allow_http_transport=False,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def canonical_lifecycle_body(event: Dict[str, Any]) -> bytes:
    payload = _json_safe(event)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_lifecycle_body(raw_body: bytes, shared_hmac_secret: str) -> str:
    return hmac.new(shared_hmac_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def default_governance(*, classification: str = "OK", reason: str = "") -> Dict[str, Any]:
    return {
        "classification": classification,
        "reason": reason,
        "follower_default_mode": "paper_only",
        "live_action_authorized": False,
    }


def build_lifecycle_order_event(
    *,
    event_type: str,
    ticker: str,
    order: Dict[str, Any],
    source_bot: str = "SERVER1-MASTER",
    event_id: str = "",
    idempotency_key: str = "",
    created_at: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    position: Optional[Dict[str, Any]] = None,
    fill: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    eid = event_id or str(uuid.uuid4())
    created = created_at or _now_iso()
    event: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": eid,
        "idempotency_key": idempotency_key or f"{source_bot}|{SCHEMA_VERSION}|{eid}",
        "source_bot": source_bot,
        "event_type": event_type,
        "ticker": str(ticker or order.get("product_id") or order.get("ticker") or "").upper(),
        "created_at": created,
        "order": _json_safe(order),
        "metadata": _json_safe(metadata or {}),
        "governance": default_governance(
            classification="WATCH" if event_type in {"d1_fill_to_position", "d3_live_exit_intent"} else "OK",
            reason="replicated_from_master_lifecycle",
        ),
        "live_order_action": False,
        "state_mutation": False,
    }
    if position is not None:
        event["position"] = _json_safe(position)
    if fill is not None:
        event["fill"] = _json_safe(fill)
    if plan is not None:
        event["plan"] = _json_safe(plan)
    if event_type == "d3_live_exit_intent":
        event.setdefault("position", {"position_id": str(order.get("linked_position_id") or "")})
        event["exit_intent"] = {
            "side": "SELL",
            "submit_live": False,
            "requires_follower_ack": True,
            "client_order_id": str(order.get("client_order_id") or ""),
            "exchange_order_id": str(order.get("exchange_order_id") or ""),
            "base_size": str(order.get("base_size") or ""),
            "limit_price": str(order.get("limit_price") or ""),
        }
    return event


def _write_jsonl(filename: str, payload: Dict[str, Any]) -> None:
    path = LOGS_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _json_safe(payload)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe_payload, ensure_ascii=False, sort_keys=True) + "\n")


def _classify_request_exception(exc: Exception) -> str:
    if isinstance(exc, requests_exceptions.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, requests_exceptions.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, requests_exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests_exceptions.SSLError):
        return "ssl_error"
    if isinstance(exc, requests_exceptions.ConnectionError):
        return "connection_error"
    if isinstance(exc, requests_exceptions.RequestException):
        return "request_exception"
    return "unexpected_exception"


class LifecycleReplicaPublisher:
    """Best-effort lifecycle publisher for master-to-follower order events."""

    def __init__(self, config: Optional[LifecyclePublishConfig] = None) -> None:
        self.config = config or LifecyclePublishConfig.disabled()
        self.session = requests.Session()

    @property
    def endpoint(self) -> str:
        base = self.config.replication_config.replica_url.rstrip("/")
        return f"{base}{LIFECYCLE_ENDPOINT}" if base else LIFECYCLE_ENDPOINT

    def build_request(self, event: Dict[str, Any]) -> Dict[str, Any]:
        valid, errors, effect = validate_lifecycle_event_v1(event)
        raw_body = canonical_lifecycle_body(event)
        secret = self.config.replication_config.shared_hmac_secret
        signature = sign_lifecycle_body(raw_body, secret) if secret else ""
        return {
            "ok": valid,
            "schema_version": event.get("schema_version"),
            "expected_schema_version": SCHEMA_VERSION,
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "ticker": event.get("ticker"),
            "errors": errors,
            "effect": effect,
            "endpoint": self.endpoint,
            "headers": {
                "Content-Type": "application/json",
                "x-replica-signature": signature,
            },
            "body_sha256": hashlib.sha256(raw_body).hexdigest(),
            "body_bytes": raw_body,
            "body": json.loads(raw_body.decode("utf-8")),
        }

    def publish_lifecycle_best_effort(self, event: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = self.build_request(event)
            if not request["ok"]:
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "schema_validation_failed",
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "errors": request["errors"],
                    "http_attempted": False,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                }

            replication_config = self.config.replication_config
            if not replication_config.enabled:
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "replication_disabled",
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "http_attempted": False,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                    "request": {
                        "endpoint": request["endpoint"],
                        "body_sha256": request["body_sha256"],
                        "signature_present": bool(request["headers"]["x-replica-signature"]),
                    },
                }

            if not self.config.lifecycle_enabled:
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "lifecycle_replication_disabled",
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "http_attempted": False,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                    "request": {
                        "endpoint": request["endpoint"],
                        "body_sha256": request["body_sha256"],
                        "signature_present": bool(request["headers"]["x-replica-signature"]),
                    },
                }

            if not self.config.allow_http_transport:
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "lifecycle_http_disabled",
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "http_attempted": False,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                    "request": {
                        "endpoint": request["endpoint"],
                        "body_sha256": request["body_sha256"],
                        "signature_present": bool(request["headers"]["x-replica-signature"]),
                        "allow_http_transport": self.config.allow_http_transport,
                    },
                }

            try:
                response = self.session.post(
                    request["endpoint"],
                    data=request["body_bytes"],
                    headers=request["headers"],
                    timeout=replication_config.timeout_seconds,
                    verify=replication_config.verify_tls,
                )
                try:
                    response_body: Any = response.json()
                except Exception:
                    response_body = {"raw_text": response.text}
                result = {
                    "ok": response.ok,
                    "skipped": False,
                    "status_code": response.status_code,
                    "response": response_body,
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "http_attempted": True,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                    "request": {
                        "endpoint": request["endpoint"],
                        "body_sha256": request["body_sha256"],
                        "signature_present": bool(request["headers"]["x-replica-signature"]),
                    },
                }
                _write_jsonl(
                    "replication_lifecycle_outbox.jsonl",
                    {
                        "timestamp": _now_iso(),
                        "status": "sent" if response.ok else "http_error",
                        "payload": request["body"],
                        "result": result,
                    },
                )
                if not response.ok:
                    logging.warning(
                        "Lifecycle replication HTTP error | ticker=%s | event_id=%s | status_code=%s",
                        event.get("ticker"),
                        event.get("event_id"),
                        response.status_code,
                    )
                return result
            except requests_exceptions.RequestException as exc:
                category = _classify_request_exception(exc)
                result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "lifecycle_replication_unavailable",
                    "error_category": category,
                    "error": str(exc) or type(exc).__name__,
                    "event_id": event.get("event_id"),
                    "event_type": event.get("event_type"),
                    "ticker": event.get("ticker"),
                    "http_attempted": True,
                    "state_write_performed": False,
                    "coinbase_call_attempted": False,
                    "request": {
                        "endpoint": request["endpoint"],
                        "body_sha256": request["body_sha256"],
                        "signature_present": bool(request["headers"]["x-replica-signature"]),
                    },
                }
                _write_jsonl(
                    "replication_lifecycle_outbox.jsonl",
                    {
                        "timestamp": _now_iso(),
                        "status": "exception",
                        "payload": request["body"],
                        "result": result,
                    },
                )
                logging.warning(
                    "Lifecycle replication unavailable | ticker=%s | event_id=%s | category=%s",
                    event.get("ticker"),
                    event.get("event_id"),
                    category,
                )
                return result

        except Exception as exc:
            return {
                "ok": False,
                "skipped": True,
                "reason": "lifecycle_publisher_exception",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "event_id": event.get("event_id") if isinstance(event, dict) else "",
                "http_attempted": False,
                "state_write_performed": False,
                "coinbase_call_attempted": False,
            }


def publish_lifecycle_event_best_effort(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        publisher = LifecycleReplicaPublisher(config=LifecyclePublishConfig.from_env())
        return publisher.publish_lifecycle_best_effort(event)
    except Exception as exc:
        return {
            "ok": False,
            "skipped": True,
            "reason": "lifecycle_publisher_init_exception",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "event_id": event.get("event_id") if isinstance(event, dict) else "",
            "event_type": event.get("event_type") if isinstance(event, dict) else "",
            "http_attempted": False,
            "state_write_performed": False,
            "coinbase_call_attempted": False,
        }


def publish_lifecycle_events_disabled_scaffold(
    events: list[Dict[str, Any]],
    *,
    config: Optional[LifecyclePublishConfig] = None,
) -> Dict[str, Any]:
    publisher = LifecycleReplicaPublisher(config=config)
    results = [publisher.publish_lifecycle_best_effort(event) for event in events]
    return {
        "generated_at": _now_iso(),
        "phase": LIFECYCLE_PHASE,
        "schema_version": SCHEMA_VERSION,
        "event_count": len(events),
        "results": results,
        "all_skipped": all(row.get("skipped") is True for row in results),
        "http_attempted": any(row.get("http_attempted") is True for row in results),
        "state_write_performed": any(row.get("state_write_performed") is True for row in results),
        "coinbase_call_attempted": any(row.get("coinbase_call_attempted") is True for row in results),
    }


__all__ = [
    "LIFECYCLE_ENDPOINT",
    "LIFECYCLE_PHASE",
    "LifecyclePublishConfig",
    "LifecycleReplicaPublisher",
    "build_lifecycle_order_event",
    "canonical_lifecycle_body",
    "default_governance",
    "publish_lifecycle_event_best_effort",
    "publish_lifecycle_events_disabled_scaffold",
    "sign_lifecycle_body",
]
