from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

D32_PHASE = "D3.2_llm_pre_live_provider_health"
D32_READY = "d32_llm_pre_live_health_ready"
D32_BLOCKED = "d32_llm_pre_live_health_blocked"
D32_DISABLED = "d32_llm_pre_live_health_disabled"

FATAL_PROVIDER_ERROR_TYPES = {
    "provider_billing_or_credit_error",
    "provider_rate_limit_or_quota_error",
    "provider_unavailable_or_overloaded",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        value = int(getattr(cfg, name, default))
        return value if value > 0 else default
    except Exception:
        return default


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _read_jsonl(path: Path, *, max_lines: int = 5000) -> Tuple[List[Dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    except Exception:
        return [], 0
    rows: List[Dict[str, Any]] = []
    invalid = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            invalid += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            invalid += 1
    return rows, invalid


def _recent_rows(rows: Iterable[Dict[str, Any]], *, since: datetime) -> Tuple[List[Dict[str, Any]], int]:
    recent: List[Dict[str, Any]] = []
    undated = 0
    for row in rows:
        dt = _parse_dt(row.get("generated_at"))
        if dt is None:
            undated += 1
            continue
        if dt >= since:
            recent.append(row)
    return recent, undated


def _counter(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, int]:
    c: Counter[str] = Counter()
    for row in rows:
        c[str(row.get(key) or "unknown")] += 1
    return dict(sorted(c.items()))


def _brief_rows(rows: Iterable[Dict[str, Any]], *, limit: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in list(rows)[-limit:]:
        out.append({
            "generated_at": row.get("generated_at"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "ticker": row.get("ticker"),
            "stage": row.get("stage"),
            "error_type": row.get("error_type"),
            "fatal_provider_error": bool(row.get("fatal_provider_error")),
            "error": str(row.get("error") or "")[:300],
            "unknown_keys": row.get("unknown_keys"),
            "counts_as_corrupt": row.get("counts_as_corrupt"),
            "raw_text_truncated": row.get("raw_text_truncated"),
            "raw_text_original_chars": row.get("raw_text_original_chars"),
        })
    return out


def build_phase_d32_llm_pre_live_health_report(
    *,
    cfg: Any,
    project_root: Path | str = Path("."),
    now: Optional[datetime] = None,
    max_lines: int = 5000,
) -> Dict[str, Any]:
    """Assess whether recent LLM/provider logs are clean enough for entry-only arming.

    This phase does not call any external provider. It only reads local logs and
    config flags. Missing timestamps are reported as warnings so old pre-D.3.2
    logs cannot masquerade as fresh evidence.
    """
    if not _cfg_bool(cfg, "enable_phase_d32_llm_pre_live_health", True):
        return {
            "generated_at": _now_iso(),
            "phase": D32_PHASE,
            "status": D32_DISABLED,
            "ready": True,
            "blockers": [],
            "warnings": ["d32_llm_pre_live_health_disabled"],
            "safety_policy": {"does_not_call_external_providers": True, "does_not_submit_orders": True},
        }

    now_dt = (now or _now_utc()).astimezone(timezone.utc)
    window_minutes = _cfg_int(cfg, "phase_d32_llm_health_window_minutes", 240)
    since = now_dt - timedelta(minutes=window_minutes)
    root = Path(project_root)
    logs = root / "logs"

    corrupt_rows, corrupt_invalid = _read_jsonl(logs / "llm_corrupt.jsonl", max_lines=max_lines)
    schema_drift_rows, schema_drift_invalid = _read_jsonl(logs / "llm_schema_drift.jsonl", max_lines=max_lines)
    provider_rows, provider_invalid = _read_jsonl(logs / "llm_provider_errors.jsonl", max_lines=max_lines)
    raw_rows, raw_invalid = _read_jsonl(logs / "llm_raw.jsonl", max_lines=min(max_lines, 1000))

    recent_corrupt, undated_corrupt = _recent_rows(corrupt_rows, since=since)
    recent_schema_drift, undated_schema_drift = _recent_rows(schema_drift_rows, since=since)
    recent_provider, undated_provider = _recent_rows(provider_rows, since=since)
    recent_raw, undated_raw = _recent_rows(raw_rows, since=since)

    fatal_provider = [
        row for row in recent_provider
        if bool(row.get("fatal_provider_error")) or str(row.get("error_type") or "") in FATAL_PROVIDER_ERROR_TYPES
    ]

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    if _cfg_bool(cfg, "enable_deepseek_preprocess", False):
        blockers.append("deepseek_preprocess_enabled_before_live_pilot")
    else:
        passed.append("deepseek_preprocess_disabled")

    if _cfg_bool(cfg, "enable_anthropic_fallback", False):
        blockers.append("anthropic_fallback_enabled_before_live_pilot")
    else:
        passed.append("anthropic_fallback_disabled")

    if _cfg_bool(cfg, "phase_d32_block_on_recent_provider_errors", True) and fatal_provider:
        blockers.append(f"recent_fatal_provider_errors:{len(fatal_provider)}")
    elif not fatal_provider:
        passed.append("no_recent_fatal_provider_errors")

    if _cfg_bool(cfg, "phase_d32_block_on_recent_llm_corrupt", True) and recent_corrupt:
        blockers.append(f"recent_llm_corrupt_outputs:{len(recent_corrupt)}")
    elif not recent_corrupt:
        passed.append("no_recent_llm_corrupt_outputs")

    if recent_schema_drift:
        warnings.append(f"recent_llm_schema_drift_extra_keys_ignored:{len(recent_schema_drift)}")
    else:
        passed.append("no_recent_llm_schema_drift")

    if undated_corrupt or undated_schema_drift or undated_provider or undated_raw:
        warnings.append(
            "undated_legacy_llm_log_rows_present:"
            f"corrupt={undated_corrupt},schema_drift={undated_schema_drift},provider={undated_provider},raw={undated_raw}"
        )
    if corrupt_invalid or schema_drift_invalid or provider_invalid or raw_invalid:
        warnings.append(
            "invalid_jsonl_rows_present:"
            f"corrupt={corrupt_invalid},schema_drift={schema_drift_invalid},provider={provider_invalid},raw={raw_invalid}"
        )

    ready = not blockers
    return _json_safe({
        "generated_at": now_dt.isoformat(),
        "phase": D32_PHASE,
        "status": D32_READY if ready else D32_BLOCKED,
        "ready": ready,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "passed_checks": passed,
        "window": {
            "minutes": window_minutes,
            "since": since.isoformat(),
        },
        "config_flags": {
            "enable_deepseek_preprocess": _cfg_bool(cfg, "enable_deepseek_preprocess", False),
            "enable_anthropic_fallback": _cfg_bool(cfg, "enable_anthropic_fallback", False),
            "openai_model": getattr(cfg, "openai_model", None),
            "openai_analyst_model": getattr(cfg, "openai_analyst_model", None),
            "openai_judge_model": getattr(cfg, "openai_judge_model", None),
            "llm_context_hygiene_enabled": _cfg_bool(cfg, "llm_context_hygiene_enabled", True),
            "llm_payload_string_max_chars": getattr(cfg, "llm_payload_string_max_chars", None),
            "llm_repeated_fragment_max_repeats": getattr(cfg, "llm_repeated_fragment_max_repeats", None),
            "phase_d32_block_on_recent_llm_corrupt": _cfg_bool(cfg, "phase_d32_block_on_recent_llm_corrupt", True),
            "phase_d32_block_on_recent_provider_errors": _cfg_bool(cfg, "phase_d32_block_on_recent_provider_errors", True),
        },
        "counts": {
            "total_corrupt_rows_sampled": len(corrupt_rows),
            "total_schema_drift_rows_sampled": len(schema_drift_rows),
            "total_provider_error_rows_sampled": len(provider_rows),
            "total_raw_rows_sampled": len(raw_rows),
            "recent_corrupt_rows": len(recent_corrupt),
            "recent_schema_drift_rows": len(recent_schema_drift),
            "recent_provider_error_rows": len(recent_provider),
            "recent_fatal_provider_errors": len(fatal_provider),
            "recent_raw_rows": len(recent_raw),
            "undated_corrupt_rows": undated_corrupt,
            "undated_schema_drift_rows": undated_schema_drift,
            "undated_provider_error_rows": undated_provider,
            "undated_raw_rows": undated_raw,
        },
        "recent_summary": {
            "corrupt_by_provider": _counter(recent_corrupt, "provider"),
            "corrupt_by_stage": _counter(recent_corrupt, "stage"),
            "corrupt_by_error_type": _counter(recent_corrupt, "error_type"),
            "schema_drift_by_provider": _counter(recent_schema_drift, "provider"),
            "schema_drift_by_stage": _counter(recent_schema_drift, "stage"),
            "schema_drift_by_error_type": _counter(recent_schema_drift, "error_type"),
            "provider_errors_by_provider": _counter(recent_provider, "provider"),
            "provider_errors_by_stage": _counter(recent_provider, "stage"),
            "provider_errors_by_error_type": _counter(recent_provider, "error_type"),
        },
        "recent_corrupt": _brief_rows(recent_corrupt),
        "recent_schema_drift": _brief_rows(recent_schema_drift),
        "recent_provider_errors": _brief_rows(recent_provider),
        "paths": {
            "llm_corrupt": str(logs / "llm_corrupt.jsonl"),
            "llm_schema_drift": str(logs / "llm_schema_drift.jsonl"),
            "llm_provider_errors": str(logs / "llm_provider_errors.jsonl"),
            "llm_raw": str(logs / "llm_raw.jsonl"),
        },
        "safety_policy": {
            "does_not_call_external_providers": True,
            "does_not_submit_orders": True,
            "recent_provider_errors_block_live_arming": _cfg_bool(cfg, "phase_d32_block_on_recent_provider_errors", True),
            "recent_corrupt_outputs_block_live_arming": _cfg_bool(cfg, "phase_d32_block_on_recent_llm_corrupt", True),
        },
    })


__all__ = [
    "D32_PHASE",
    "D32_READY",
    "D32_BLOCKED",
    "build_phase_d32_llm_pre_live_health_report",
]
