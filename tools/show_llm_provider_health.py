#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_jsonl_tail(path: Path, limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _counter(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    c: Counter[str] = Counter()
    for row in rows:
        value = str(row.get(key) or "unknown")
        c[value] += 1
    return dict(sorted(c.items()))


def build_llm_provider_health(project_root: Path = PROJECT_ROOT, sample: int = 200) -> Dict[str, Any]:
    logs = project_root / "logs"
    corrupt = _read_jsonl_tail(logs / "llm_corrupt.jsonl", sample)
    schema_drift = _read_jsonl_tail(logs / "llm_schema_drift.jsonl", sample)
    provider_errors = _read_jsonl_tail(logs / "llm_provider_errors.jsonl", sample)
    raw = _read_jsonl_tail(logs / "llm_raw.jsonl", min(sample, 50))

    return {
        "sample_size": sample,
        "paths": {
            "llm_corrupt": str(logs / "llm_corrupt.jsonl"),
            "llm_schema_drift": str(logs / "llm_schema_drift.jsonl"),
            "llm_provider_errors": str(logs / "llm_provider_errors.jsonl"),
            "llm_raw": str(logs / "llm_raw.jsonl"),
        },
        "llm_corrupt_sample_size": len(corrupt),
        "llm_schema_drift_sample_size": len(schema_drift),
        "provider_error_sample_size": len(provider_errors),
        "raw_sample_size": len(raw),
        "corrupt_by_provider": _counter(corrupt, "provider"),
        "corrupt_by_stage": _counter(corrupt, "stage"),
        "corrupt_by_error_type": _counter(corrupt, "error_type"),
        "schema_drift_by_provider": _counter(schema_drift, "provider"),
        "schema_drift_by_stage": _counter(schema_drift, "stage"),
        "schema_drift_by_error_type": _counter(schema_drift, "error_type"),
        "provider_errors_by_provider": _counter(provider_errors, "provider"),
        "provider_errors_by_stage": _counter(provider_errors, "stage"),
        "provider_errors_by_error_type": _counter(provider_errors, "error_type"),
        "recent_provider_errors": provider_errors[-10:],
        "recent_corrupt": [
            {
                "provider": row.get("provider"),
                "model": row.get("model"),
                "ticker": row.get("ticker"),
                "stage": row.get("stage"),
                "error_type": row.get("error_type"),
                "error": str(row.get("error") or "")[:500],
                "raw_text_truncated": row.get("raw_text_truncated"),
                "raw_text_original_chars": row.get("raw_text_original_chars"),
            }
            for row in corrupt[-10:]
        ],
        "recent_schema_drift": [
            {
                "provider": row.get("provider"),
                "model": row.get("model"),
                "ticker": row.get("ticker"),
                "stage": row.get("stage"),
                "error_type": row.get("error_type"),
                "unknown_keys": row.get("unknown_keys"),
                "counts_as_corrupt": bool(row.get("counts_as_corrupt")),
            }
            for row in schema_drift[-10:]
        ],
        "safety_policy": "LLM/provider failures must fall back to wait/no_trade and must never authorize execution.",
    }


def print_report(report: Dict[str, Any]) -> None:
    print("LLM/provider health")
    print("===================")
    print("llm_corrupt_sample_size:", report.get("llm_corrupt_sample_size"))
    print("llm_schema_drift_sample_size:", report.get("llm_schema_drift_sample_size"))
    print("provider_error_sample_size:", report.get("provider_error_sample_size"))
    print("corrupt_by_provider:", json.dumps(report.get("corrupt_by_provider", {}), ensure_ascii=False, sort_keys=True))
    print("corrupt_by_stage:", json.dumps(report.get("corrupt_by_stage", {}), ensure_ascii=False, sort_keys=True))
    print("schema_drift_by_stage:", json.dumps(report.get("schema_drift_by_stage", {}), ensure_ascii=False, sort_keys=True))
    print("provider_errors_by_provider:", json.dumps(report.get("provider_errors_by_provider", {}), ensure_ascii=False, sort_keys=True))
    print("provider_errors_by_error_type:", json.dumps(report.get("provider_errors_by_error_type", {}), ensure_ascii=False, sort_keys=True))
    print("Safety:", report.get("safety_policy"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon LLM/provider error-hygiene status.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output")
    parser.add_argument("--sample", type=int, default=200, help="Aantal regels per logbestand in sample")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="Projectroot")
    args = parser.parse_args()

    report = build_llm_provider_health(Path(args.project_root), max(1, int(args.sample)))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
