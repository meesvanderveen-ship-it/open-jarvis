from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests import exceptions as requests_exceptions

from replication.config import ReplicationConfig
from replication.models import ReplicationEnvelope


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


class ReplicaPublisher:
    def __init__(self, config: Optional[ReplicationConfig] = None) -> None:
        self.config = config or ReplicationConfig.from_env()
        self.session = requests.Session()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            out.append(str(item))
        return out

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): ReplicaPublisher._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [ReplicaPublisher._json_safe(v) for v in value]
        return value

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except Exception:
            return default

    @staticmethod
    def _normalize_side(side: Any) -> str:
        text = str(side or "").strip().upper()
        if text in {"BUY", "LONG"}:
            return "BUY"
        if text in {"SELL", "REDUCE", "CLOSE"}:
            return "SELL"
        return text or "BUY"

    @staticmethod
    def _normalize_decision(decision: Any, side: str) -> str:
        text = str(decision or "").strip().lower()

        if text:
            return text

        if side == "BUY":
            return "approve_trade"
        return "reduce_position"

    @staticmethod
    def _write_jsonl(filename: str, payload: Dict[str, Any]) -> None:
        path = LOGS_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_payload = ReplicaPublisher._json_safe(payload)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")

    def _sign_body(self, raw_body: bytes) -> str:
        return hmac.new(
            self.config.shared_hmac_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
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

    @staticmethod
    def _short_exception_message(exc: Exception) -> str:
        text = str(exc).strip()
        if text:
            return text
        return exc.__class__.__name__

    def _log_publish_warning(
        self,
        *,
        ticker: str,
        event_id: str,
        category: str,
        message: str,
    ) -> None:
        logging.warning(
            "Replication unavailable | ticker=%s | event_id=%s | category=%s | detail=%s",
            ticker,
            event_id,
            category,
            message,
        )

    def build_envelope(
        self,
        *,
        ticker: str,
        decision: str,
        side: str,
        strategy: Optional[str] = None,
        setup_type: Optional[str] = None,
        confidence: int = 0,
        requested_size_quote: float = 0.0,
        requested_size_base: float = 0.0,
        reason_summary: Optional[list[str]] = None,
        must_reject_if: Optional[list[str]] = None,
        analysis: Optional[Dict[str, Any]] = None,
        entry_gate: Optional[Dict[str, Any]] = None,
        risk_context: Optional[Dict[str, Any]] = None,
        position_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> ReplicationEnvelope:
        return ReplicationEnvelope(
            event_id=event_id or str(uuid.uuid4()),
            timestamp=self._now_iso(),
            source_bot=self.config.source_bot_name,
            ticker=ticker.upper().strip(),
            decision=str(decision).strip(),
            side=str(side).strip().upper(),
            strategy=strategy,
            setup_type=setup_type,
            confidence=int(confidence or 0),
            requested_size_quote=float(requested_size_quote or 0.0),
            requested_size_base=float(requested_size_base or 0.0),
            reason_summary=self._safe_list(reason_summary),
            must_reject_if=self._safe_list(must_reject_if),
            analysis=self._json_safe(self._safe_dict(analysis)),
            entry_gate=self._json_safe(self._safe_dict(entry_gate)),
            risk_context=self._json_safe(self._safe_dict(risk_context)),
            position_context=self._json_safe(self._safe_dict(position_context)),
            metadata=self._json_safe(self._safe_dict(metadata)),
        )

    def publish_decision_best_effort(
        self,
        *,
        ticker: str,
        decision: Any,
        side: Any,
        strategy: Optional[str] = None,
        setup_type: Optional[str] = None,
        confidence: Any = 0,
        requested_size_quote: Any = 0.0,
        requested_size_base: Any = 0.0,
        reason_summary: Optional[list[str]] = None,
        must_reject_if: Optional[list[str]] = None,
        analysis: Optional[Dict[str, Any]] = None,
        entry_gate: Optional[Dict[str, Any]] = None,
        risk_context: Optional[Dict[str, Any]] = None,
        position_context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Best-effort helper for server 1:
        - never raises
        - normalizes payload
        - publishes to server 2 if enabled
        - returns a structured result
        """
        try:
            normalized_side = self._normalize_side(side)
            normalized_decision = self._normalize_decision(decision, normalized_side)
            size_quote = self._safe_float(requested_size_quote, 0.0)
            size_base = self._safe_float(requested_size_base, 0.0)
            conf = self._safe_int(confidence, 0)

            safe_metadata = self._safe_dict(metadata).copy()

            if size_quote > 0 and "quote_size" not in safe_metadata:
                safe_metadata["quote_size"] = f"{size_quote:.2f}"
            if size_base > 0 and "base_size" not in safe_metadata:
                safe_metadata["base_size"] = f"{size_base:.8f}"

            envelope = self.build_envelope(
                ticker=ticker,
                decision=normalized_decision,
                side=normalized_side,
                strategy=strategy,
                setup_type=setup_type,
                confidence=conf,
                requested_size_quote=size_quote,
                requested_size_base=size_base,
                reason_summary=reason_summary,
                must_reject_if=must_reject_if,
                analysis=analysis,
                entry_gate=entry_gate,
                risk_context=risk_context,
                position_context=position_context,
                metadata=safe_metadata,
                event_id=event_id,
            )

            result = self.publish(envelope)

            logging.info(
                "Replication publish result | ticker=%s | event_id=%s | ok=%s | skipped=%s | reason=%s",
                envelope.ticker,
                envelope.event_id,
                result.get("ok"),
                result.get("skipped"),
                result.get("reason"),
            )
            return result

        except Exception as e:
            category = self._classify_request_exception(e)
            message = self._short_exception_message(e)

            safe_result = {
                "ok": False,
                "skipped": True,
                "reason": "replication_unavailable",
                "error_category": category,
                "error": message,
                "event_id": event_id or "",
                "ticker": str(ticker or "").upper().strip(),
            }

            self._write_jsonl(
                "replication_outbox.jsonl",
                {
                    "timestamp": self._now_iso(),
                    "status": "publisher_helper_exception",
                    "payload": {
                        "ticker": ticker,
                        "decision": decision,
                        "side": side,
                        "strategy": strategy,
                        "setup_type": setup_type,
                        "confidence": confidence,
                        "requested_size_quote": requested_size_quote,
                        "requested_size_base": requested_size_base,
                        "reason_summary": self._safe_list(reason_summary),
                        "must_reject_if": self._safe_list(must_reject_if),
                        "analysis": self._safe_dict(analysis),
                        "entry_gate": self._safe_dict(entry_gate),
                        "risk_context": self._safe_dict(risk_context),
                        "position_context": self._safe_dict(position_context),
                        "metadata": self._safe_dict(metadata),
                        "event_id": event_id,
                    },
                    "result": safe_result,
                },
            )

            self._log_publish_warning(
                ticker=str(ticker or "").upper().strip(),
                event_id=str(event_id or ""),
                category=category,
                message=message,
            )
            return safe_result

    def publish(self, envelope: ReplicationEnvelope) -> Dict[str, Any]:
        if not self.config.enabled:
            result = {
                "ok": False,
                "skipped": True,
                "reason": "replication_disabled",
                "event_id": envelope.event_id,
                "ticker": envelope.ticker,
            }
            self._write_jsonl(
                "replication_outbox.jsonl",
                {
                    "timestamp": self._now_iso(),
                    "status": "skipped",
                    "payload": envelope.to_dict(),
                    "result": result,
                },
            )
            return result

        payload = self._json_safe(envelope.to_dict())
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = self._sign_body(raw)
        url = f"{self.config.replica_url}/api/replica/decision"

        try:
            response = self.session.post(
                url,
                data=raw,
                headers={
                    "Content-Type": "application/json",
                    "x-replica-signature": signature,
                },
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_tls,
            )

            response_text = response.text
            try:
                response_json = response.json()
            except Exception:
                response_json = {"raw_text": response_text}

            result = {
                "ok": response.ok,
                "status_code": response.status_code,
                "response": response_json,
                "event_id": envelope.event_id,
                "ticker": envelope.ticker,
            }

            self._write_jsonl(
                "replication_outbox.jsonl",
                {
                    "timestamp": self._now_iso(),
                    "status": "sent" if response.ok else "http_error",
                    "payload": payload,
                    "result": result,
                },
            )

            if not response.ok:
                logging.warning(
                    "Replication HTTP error | ticker=%s | event_id=%s | status_code=%s | response=%s",
                    envelope.ticker,
                    envelope.event_id,
                    response.status_code,
                    response_json,
                )

            return result

        except requests_exceptions.RequestException as e:
            category = self._classify_request_exception(e)
            message = self._short_exception_message(e)

            result = {
                "ok": False,
                "skipped": True,
                "reason": "replication_unavailable",
                "error_category": category,
                "error": message,
                "event_id": envelope.event_id,
                "ticker": envelope.ticker,
            }

            self._write_jsonl(
                "replication_outbox.jsonl",
                {
                    "timestamp": self._now_iso(),
                    "status": "exception",
                    "payload": payload,
                    "result": result,
                },
            )

            self._log_publish_warning(
                ticker=envelope.ticker,
                event_id=envelope.event_id,
                category=category,
                message=message,
            )
            return result

        except Exception as e:
            category = self._classify_request_exception(e)
            message = self._short_exception_message(e)

            result = {
                "ok": False,
                "skipped": True,
                "reason": "replication_unavailable",
                "error_category": category,
                "error": message,
                "event_id": envelope.event_id,
                "ticker": envelope.ticker,
            }

            self._write_jsonl(
                "replication_outbox.jsonl",
                {
                    "timestamp": self._now_iso(),
                    "status": "exception",
                    "payload": payload,
                    "result": result,
                },
            )

            self._log_publish_warning(
                ticker=envelope.ticker,
                event_id=envelope.event_id,
                category=category,
                message=message,
            )
            return result
