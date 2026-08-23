"""Shadow Outcome Accelerator service — read-only evidence from shadow decisions.

Reads from:
- reports/parameter_optimization/shadow-outcome-accelerator-latest.json (pre-generated report)
- state/shadow_decision_outcomes.jsonl (raw records for recent/coverage/patterns)

Never writes anything. Never calls Coinbase. Never calls run_governor(apply=True).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dashboard.backend import cache
from dashboard.backend.config import PROJECT_ROOT
from dashboard.backend.services.util import read_json_file

_REPORT_JSON = PROJECT_ROOT / "reports" / "parameter_optimization" / "shadow-outcome-accelerator-latest.json"
_STORE_JSONL = PROJECT_ROOT / "state" / "shadow_decision_outcomes.jsonl"


def _read_jsonl(path: Path, max_lines: int = 2000) -> list[dict]:
    """Read a JSONL file and return parsed dicts (graceful on missing/corrupt)."""
    if not path.is_file():
        return []
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if len(records) >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        records.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records


def _empty_status() -> dict:
    return {
        "generated_at": None,
        "schema_version": "shadow_outcome_accelerator_v1",
        "total_shadow_decisions": 0,
        "status_counts": {},
        "evaluations_by_horizon": {
            "1h": {"pending": 0, "complete": 0, "insufficient_data": 0},
            "4h": {"pending": 0, "complete": 0, "insufficient_data": 0},
            "24h": {"pending": 0, "complete": 0, "insufficient_data": 0},
        },
        "usable_evidence_count": 0,
        "evidence_quality_score": 0.0,
        "by_ticker": {},
        "by_regime": {},
        "top_missed_opportunity_patterns": [],
        "top_bad_trade_avoided_patterns": [],
        "quality_distribution": {},
        "sufficient_for_optimization": False,
        "sufficiency_note": "No shadow records yet.",
        "learning_policy": (
            "Shadow evidence is observation-only. No live execution authority. "
            "No parameter auto-apply outside the approved-profile/governor route."
        ),
        "no_live_orders": True,
        "no_coinbase_calls": True,
        "no_parameter_mutation": True,
        "source": "no_data",
    }


def _compute_status() -> dict:
    # Prefer live JSONL (always up-to-date) over pre-generated report JSON (may be stale).
    # Fall back to report JSON only when JSONL is empty.
    records = _read_jsonl(_STORE_JSONL)
    if not records:
        data = read_json_file(_REPORT_JSON, None)
        if isinstance(data, dict) and data.get("total_shadow_decisions") is not None:
            data["source"] = "report_json"
            return data
        return _empty_status()

    total = len(records)
    status_counts: dict = {}
    eval_counts: dict = {
        "1h": {"pending": 0, "complete": 0, "insufficient_data": 0},
        "4h": {"pending": 0, "complete": 0, "insufficient_data": 0},
        "24h": {"pending": 0, "complete": 0, "insufficient_data": 0},
    }
    by_ticker: dict = {}
    by_regime: dict = {}
    usable = 0
    missed_pat: dict = {}
    avoided_pat: dict = {}
    quality_dist: dict = {}

    for rec in records:
        st = str(rec.get("status") or "pending")
        status_counts[st] = status_counts.get(st, 0) + 1
        by_ticker[str(rec.get("ticker") or "UNKNOWN")] = by_ticker.get(str(rec.get("ticker") or "UNKNOWN"), 0) + 1
        by_regime[str(rec.get("market_regime") or "unknown")] = by_regime.get(str(rec.get("market_regime") or "unknown"), 0) + 1
        evals = rec.get("evaluations") or {}
        for hk in ("1h", "4h", "24h"):
            ev = evals.get(hk)
            b = eval_counts.setdefault(hk, {"pending": 0, "complete": 0, "insufficient_data": 0})
            if ev is None:
                b["pending"] += 1
            elif ev.get("status") == "insufficient_data":
                b["insufficient_data"] += 1
            else:
                b["complete"] += 1
                if ev.get("evidence_usable"):
                    usable += 1
                q = str(ev.get("evidence_quality") or "unknown")
                quality_dist[q] = quality_dist.get(q, 0) + 1
                if ev.get("missed_opportunity_label") == "yes":
                    k = str(rec.get("setup_type") or "unknown")
                    missed_pat[k] = missed_pat.get(k, 0) + 1
                if ev.get("bad_trade_avoided_label") == "yes":
                    k = str(rec.get("decision") or "unknown")
                    avoided_pat[k] = avoided_pat.get(k, 0) + 1

    total_complete = sum(eval_counts.get(h, {}).get("complete", 0) for h in ("1h", "4h", "24h"))
    quality_score = round(usable / max(1, total_complete), 3)
    sufficient = total >= 50 and usable >= 20

    return {
        "generated_at": records[-1].get("timestamp") if records else None,
        "schema_version": "shadow_outcome_accelerator_v1",
        "total_shadow_decisions": total,
        "status_counts": status_counts,
        "evaluations_by_horizon": eval_counts,
        "usable_evidence_count": usable,
        "evidence_quality_score": quality_score,
        "by_ticker": by_ticker,
        "by_regime": by_regime,
        "top_missed_opportunity_patterns": [
            {"setup_type": k, "count": v}
            for k, v in sorted(missed_pat.items(), key=lambda x: -x[1])[:5]
        ],
        "top_bad_trade_avoided_patterns": [
            {"decision": k, "count": v}
            for k, v in sorted(avoided_pat.items(), key=lambda x: -x[1])[:5]
        ],
        "quality_distribution": quality_dist,
        "sufficient_for_optimization": sufficient,
        "sufficiency_note": (
            "Sufficient for qualitative review (>=50 records, >=20 usable evaluations)"
            if sufficient
            else f"Not yet sufficient: {total} shadow records, {usable} usable evaluations (need >=50 records, >=20 usable)"
        ),
        "learning_policy": (
            "Shadow evidence is observation-only. No live execution authority. "
            "No parameter auto-apply outside the approved-profile/governor route."
        ),
        "no_live_orders": True,
        "no_coinbase_calls": True,
        "no_parameter_mutation": True,
        "source": "jsonl_derived",
    }


def get_shadow_outcomes_status() -> dict:
    return cache.get_or_compute("shadow_outcomes_status", _compute_status, ttl_seconds=30)


def get_shadow_outcomes_recent(limit: int = 20) -> dict:
    def _compute() -> dict:
        records = _read_jsonl(_STORE_JSONL)
        recent = records[-limit:] if len(records) > limit else records
        recent = list(reversed(recent))  # newest first
        # Strip potentially large raw fields
        compact = []
        for r in recent:
            compact.append({
                "shadow_id": r.get("shadow_id"),
                "ticker": r.get("ticker"),
                "timestamp": r.get("timestamp"),
                "decision": r.get("decision"),
                "status": r.get("status"),
                "market_regime": r.get("market_regime"),
                "setup_type": r.get("setup_type"),
                "bull_score": r.get("bull_score"),
                "bear_score": r.get("bear_score"),
                "synth_confidence": r.get("synth_confidence"),
                "mid_price": r.get("mid_price"),
                "evaluations": {
                    hk: {
                        "status": (ev or {}).get("status"),
                        "evidence_quality": (ev or {}).get("evidence_quality"),
                        "evidence_usable": (ev or {}).get("evidence_usable"),
                        "price_move_pct": (ev or {}).get("price_move_pct"),
                        "bad_trade_avoided_label": (ev or {}).get("bad_trade_avoided_label"),
                        "missed_opportunity_label": (ev or {}).get("missed_opportunity_label"),
                    }
                    for hk, ev in (r.get("evaluations") or {}).items()
                },
                "due_at": r.get("due_at"),
            })
        return {
            "total_records": len(records),
            "returned": len(compact),
            "limit": limit,
            "records": compact,
        }
    return cache.get_or_compute(f"shadow_outcomes_recent_{limit}", _compute, ttl_seconds=20)


def get_shadow_outcomes_coverage() -> dict:
    status = get_shadow_outcomes_status()
    return {
        "generated_at": status.get("generated_at"),
        "total_shadow_decisions": status.get("total_shadow_decisions", 0),
        "by_ticker": status.get("by_ticker", {}),
        "by_regime": status.get("by_regime", {}),
        "evaluations_by_horizon": status.get("evaluations_by_horizon", {}),
        "quality_distribution": status.get("quality_distribution", {}),
        "sufficient_for_optimization": status.get("sufficient_for_optimization", False),
        "sufficiency_note": status.get("sufficiency_note", ""),
        "usable_evidence_count": status.get("usable_evidence_count", 0),
        "evidence_quality_score": status.get("evidence_quality_score", 0.0),
    }


def get_shadow_outcomes_patterns() -> dict:
    status = get_shadow_outcomes_status()
    return {
        "generated_at": status.get("generated_at"),
        "top_missed_opportunity_patterns": status.get("top_missed_opportunity_patterns", []),
        "top_bad_trade_avoided_patterns": status.get("top_bad_trade_avoided_patterns", []),
        "usable_evidence_count": status.get("usable_evidence_count", 0),
        "learning_policy": status.get("learning_policy", ""),
        "no_live_orders": True,
        "no_coinbase_calls": True,
        "no_parameter_mutation": True,
    }
