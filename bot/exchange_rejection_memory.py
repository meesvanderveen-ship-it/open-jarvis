from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PRECISION_REJECT_REASONS = {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"}


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(row: Dict[str, Any], *keys: str) -> Any:
    cur: Any = row
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _ticker(row: Dict[str, Any]) -> str:
    submit = _as_dict(row.get("submit_result"))
    payload = _as_dict(submit.get("payload"))
    preview = _as_dict(payload.get("coinbase_payload_preview"))
    return str(
        row.get("ticker")
        or submit.get("ticker")
        or payload.get("ticker")
        or payload.get("product_id")
        or preview.get("product_id")
        or _nested(row, "local_order_record", "ticker")
        or ""
    ).strip().upper().replace("/", "-")


def _reject_reason(row: Dict[str, Any]) -> str:
    submit = _as_dict(row.get("submit_result"))
    adapter = _as_dict(submit.get("coinbase_submit_adapter"))
    local = _as_dict(row.get("local_order_record"))
    response = _as_dict(row.get("coinbase_response") or submit.get("coinbase_response") or local.get("coinbase_response") or adapter.get("raw_response"))
    error_response = _as_dict(response.get("error_response"))
    return str(
        row.get("reject_reason")
        or submit.get("reject_reason")
        or adapter.get("reject_reason")
        or local.get("reject_reason")
        or error_response.get("error")
        or row.get("preview_failure_reason")
        or submit.get("preview_failure_reason")
        or local.get("preview_failure_reason")
        or ""
    ).strip()


def _reject_message(row: Dict[str, Any]) -> str:
    submit = _as_dict(row.get("submit_result"))
    adapter = _as_dict(submit.get("coinbase_submit_adapter"))
    local = _as_dict(row.get("local_order_record"))
    response = _as_dict(row.get("coinbase_response") or submit.get("coinbase_response") or local.get("coinbase_response") or adapter.get("raw_response"))
    error_response = _as_dict(response.get("error_response"))
    return str(
        row.get("reject_message")
        or submit.get("reject_message")
        or adapter.get("reject_message")
        or local.get("reject_message")
        or error_response.get("message")
        or adapter.get("error")
        or ""
    ).strip()


def _payload_summary(row: Dict[str, Any]) -> str:
    submit = _as_dict(row.get("submit_result"))
    payload = _as_dict(submit.get("payload"))
    preview = _as_dict(payload.get("coinbase_payload_preview"))
    gtc = _nested(preview, "order_configuration", "limit_limit_gtc") or {}
    parts = {
        "price": payload.get("limit_price") or gtc.get("limit_price"),
        "base": payload.get("size_base_normalized") or gtc.get("base_size"),
        "quote": payload.get("size_quote_normalized") or payload.get("size_quote_requested"),
        "post_only": gtc.get("post_only"),
    }
    return json.dumps({k: v for k, v in parts.items() if v not in (None, "")}, sort_keys=True)


def summarize_recent_exchange_rejections(
    path: str | Path = "logs/phase_c_live_submit.jsonl",
    *,
    ticker: str = "",
    hours: int = 168,
    limit: int = 20,
) -> Dict[str, Any]:
    log_path = Path(path)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    selected: List[Dict[str, Any]] = []
    wanted = str(ticker or "").strip().upper().replace("/", "-")
    for row in _iter_jsonl(log_path):
        reason = _reject_reason(row)
        if not reason:
            continue
        ts = _parse_time(row.get("generated_at") or _nested(row, "submit_result", "generated_at") or row.get("created_at"))
        if ts and ts < cutoff:
            continue
        row_ticker = _ticker(row)
        if wanted and row_ticker != wanted:
            continue
        selected.append({
            "generated_at": ts.isoformat() if ts else str(row.get("generated_at") or ""),
            "ticker": row_ticker,
            "reject_reason": reason,
            "reject_message": _reject_message(row),
            "payload_summary": _payload_summary(row),
        })

    by_ticker: Dict[str, Counter] = defaultdict(Counter)
    for item in selected:
        by_ticker[item["ticker"] or "UNKNOWN"][item["reject_reason"]] += 1
    precision_counts = Counter(item["reject_reason"] for item in selected if item["reject_reason"] in PRECISION_REJECT_REASONS)
    last = max((item.get("generated_at") or "" for item in selected), default="")
    return {
        "source_path": str(log_path),
        "hours": int(hours),
        "ticker": wanted,
        "recent_rejections": dict(sorted(precision_counts.items())),
        "reject_reasons_by_ticker": {k: dict(v) for k, v in sorted(by_ticker.items())},
        "last_reject_at": last,
        "events": selected[-limit:],
        "recommended_context_warning": (
            "Recent Coinbase rejects indicate precision normalization must be applied before submit."
            if precision_counts
            else ""
        ),
    }


def recent_rejections_for_context(
    *,
    root: str | Path = ".",
    ticker: str = "",
    hours: int = 168,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    report = summarize_recent_exchange_rejections(Path(root) / "logs/phase_c_live_submit.jsonl", ticker=ticker, hours=hours, limit=limit)
    return list(report.get("events") or [])


__all__ = [
    "PRECISION_REJECT_REASONS",
    "recent_rejections_for_context",
    "summarize_recent_exchange_rejections",
]
