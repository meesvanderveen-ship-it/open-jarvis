#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text

DEFAULT_JSON = Path("reports/audits/workflow-runtime-funnel-latest.json")
DEFAULT_MD = Path("reports/audits/workflow-runtime-funnel-latest.md")


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
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


def _nested(row: Dict[str, Any], *keys: str) -> Any:
    cur: Any = row
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _attempt_row(row: Dict[str, Any]) -> Dict[str, Any]:
    submit = row.get("submit_result") if isinstance(row.get("submit_result"), dict) else row
    payload = submit.get("payload") if isinstance(submit.get("payload"), dict) else {}
    preview = payload.get("coinbase_payload_preview") if isinstance(payload.get("coinbase_payload_preview"), dict) else {}
    gtc = _nested(preview, "order_configuration", "limit_limit_gtc") or {}
    adapter = submit.get("coinbase_submit_adapter") if isinstance(submit.get("coinbase_submit_adapter"), dict) else {}
    precision = payload.get("precision_normalization") if isinstance(payload.get("precision_normalization"), dict) else {}
    product_rules = payload.get("product_rules") if isinstance(payload.get("product_rules"), dict) else payload.get("product_rules_used") if isinstance(payload.get("product_rules_used"), dict) else {}
    feasibility = payload.get("execution_feasibility") if isinstance(payload.get("execution_feasibility"), dict) else {}
    return {
        "generated_at": row.get("generated_at") or submit.get("generated_at") or "",
        "ticker": row.get("ticker") or submit.get("ticker") or payload.get("ticker") or "",
        "client_order_id": row.get("client_order_id") or submit.get("client_order_id") or payload.get("client_order_id") or preview.get("client_order_id") or "",
        "limit_price": payload.get("limit_price") or gtc.get("limit_price") or _nested(row, "risk_snapshot", "limit_price") or "",
        "quote_size": payload.get("size_quote_normalized") or payload.get("size_quote_requested") or _nested(row, "risk_snapshot", "quote_size") or "",
        "base_size": payload.get("size_base_normalized") or gtc.get("base_size") or "",
        "post_only": gtc.get("post_only", payload.get("post_only", "")),
        "method_used": adapter.get("client_method") or "",
        "payload_valid": bool(payload.get("accepted", False)),
        "precision_normalized": bool(precision),
        "precision_context_available": bool(product_rules.get("precision_context_available")),
        "execution_feasibility_available": bool(feasibility),
        "execution_feasibility_blockers": feasibility.get("blockers") or precision.get("blockers") or [],
        "coinbase_call_attempted": bool(submit.get("live_submission_attempted")),
        "live_submission_attempted": bool(row.get("live_submission_attempted") or submit.get("live_submission_attempted")),
        "live_order_submitted": bool(row.get("live_order_submitted") or submit.get("live_order_submitted")),
        "exchange_order_id": row.get("exchange_order_id") or submit.get("exchange_order_id") or "",
        "error": submit.get("error") or adapter.get("error") or "",
        "reject_reason": submit.get("reject_reason") or adapter.get("reject_reason") or "",
        "before_or_after_client_fix": "after_client_fix" if adapter.get("client_method") else "before_or_uninstrumented",
        "before_or_after_service_restart": "unknown",
    }


def _parse_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _funnel_counts(attempt_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    submitted = [r for r in attempt_rows if r["live_order_submitted"]]
    reject_counts = Counter(r["reject_reason"] or r["error"] or "unknown" for r in attempt_rows if not r["live_order_submitted"])
    return {
        "live_submission_attempted_count": len(attempt_rows),
        "live_order_submitted_count": len(submitted),
        "reject_reason_counts": dict(reject_counts),
        "precision_normalized_attempt_count": sum(1 for r in attempt_rows if r.get("precision_normalized")),
        "precision_context_missing_attempt_count": sum(1 for r in attempt_rows if not r.get("precision_context_available")),
        "invalid_price_precision_reject_count": reject_counts.get("INVALID_PRICE_PRECISION", 0),
        "invalid_size_precision_reject_count": reject_counts.get("INVALID_SIZE_PRECISION", 0),
    }


def build_runtime_funnel(root: str | Path = ".") -> Dict[str, Any]:
    root = Path(root)
    decisions = list(_read_jsonl(root / "logs/decision_outcomes.jsonl"))
    submit_rows = list(_read_jsonl(root / "logs/phase_c_live_submit.jsonl"))
    attempt_rows = [_attempt_row(r) for r in submit_rows if bool(r.get("live_submission_attempted") or _nested(r, "submit_result", "live_submission_attempted"))]
    submitted = [r for r in attempt_rows if r["live_order_submitted"]]
    reject_counts = Counter(r["reject_reason"] or r["error"] or "unknown" for r in attempt_rows if not r["live_order_submitted"])
    decision_records = []
    for event in decisions:
        records = event.get("records")
        if isinstance(records, list):
            decision_records.extend([r for r in records if isinstance(r, dict)])
    latest = max((_parse_time(r.get("generated_at")) for r in attempt_rows), default=datetime.min.replace(tzinfo=timezone.utc))
    recent_cutoff = latest - timedelta(hours=24) if latest.year > 2000 else latest
    recent_attempt_rows = [r for r in attempt_rows if _parse_time(r.get("generated_at")) >= recent_cutoff]
    all_time = _funnel_counts(attempt_rows)
    recent = _funnel_counts(recent_attempt_rows)
    return {
        "decision_rows_total": len(decision_records),
        "prepared_plan_rows": sum(1 for r in decision_records if r.get("decision_category") == "prepared_plan"),
        "phase_c_submit_log_rows": len(submit_rows),
        "recent_window_hours": 24,
        "recent_window_cutoff": recent_cutoff.isoformat().replace("+00:00", "Z") if latest.year > 2000 else "",
        "live_submission_attempted_count": recent["live_submission_attempted_count"],
        "live_order_submitted_count": recent["live_order_submitted_count"],
        "reject_reason_counts": recent["reject_reason_counts"],
        "precision_normalized_attempt_count": recent["precision_normalized_attempt_count"],
        "precision_context_missing_attempt_count": recent["precision_context_missing_attempt_count"],
        "invalid_price_precision_reject_count": recent["invalid_price_precision_reject_count"],
        "invalid_size_precision_reject_count": recent["invalid_size_precision_reject_count"],
        "attempt_rows": recent_attempt_rows[-50:],
        "all_time": {
            **all_time,
            "attempt_rows": attempt_rows[-50:],
        },
        "read_only": True,
        "coinbase_call_attempted_by_tool": False,
    }


def _md(report: Dict[str, Any]) -> str:
    lines = [
        "# Workflow Runtime Funnel",
        "",
        f"- decision_rows_total: `{report['decision_rows_total']}`",
        f"- prepared_plan_rows: `{report['prepared_plan_rows']}`",
        f"- phase_c_submit_log_rows: `{report['phase_c_submit_log_rows']}`",
        f"- live_submission_attempted_count: `{report['live_submission_attempted_count']}`",
        f"- live_order_submitted_count: `{report['live_order_submitted_count']}`",
        f"- reject_reason_counts: `{json.dumps(report['reject_reason_counts'], sort_keys=True)}`",
        f"- precision_normalized_attempt_count: `{report.get('precision_normalized_attempt_count', 0)}`",
        f"- precision_context_missing_attempt_count: `{report.get('precision_context_missing_attempt_count', 0)}`",
        f"- invalid_price_precision_reject_count: `{report.get('invalid_price_precision_reject_count', 0)}`",
        f"- invalid_size_precision_reject_count: `{report.get('invalid_size_precision_reject_count', 0)}`",
        "",
        "Tool is read-only; it did not call Coinbase.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only workflow runtime funnel.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_runtime_funnel(args.root)
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "live_submission_attempted_count": report["live_submission_attempted_count"], "live_order_submitted_count": report["live_order_submitted_count"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
