from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.adaptive_policy_lab import (
    CURRENT_PARAMETER_DEFAULTS,
    LABEL_PRESSURE_WEIGHTS,
    _conclusion_quality_score,
    _market_regime,
    build_regime_enrichment_fields,
    is_validated_conclusion,
    map_pressure_to_parameter,
    stable_payload_hash,
)
from bot.atomic_io import atomic_write_json
from bot.growbot_river_learning_contract import sanitize_learning_context_snapshot
from bot.reflection_learning_context import SOURCE_POLICY, isoformat_z, now_utc, parse_time, render_report_markdown


REFLECTION_LEDGER_PATH = Path("reports/reflection/history/reflection-evaluations.jsonl")
REFLECTION_SNAPSHOT_DIR = Path("reports/reflection/snapshots")
PARAMETER_PRESSURE_LEDGER_PATH = Path("reports/adaptive_policy/history/parameter-pressure-events.jsonl")

REFLECTION_SCHEMA_VERSION = "reflection_evaluation_v1"
PRESSURE_SCHEMA_VERSION = "parameter_pressure_event_v1"
CREATED_BY = "reflection_learning_context"

RUNTIME_ONLY_FIELDS = {
    "event_id",
    "evaluated_at",
    "created_at",
    "source_hash",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _stable_hash(payload: Dict[str, Any], *, exclude: Iterable[str] = ()) -> str:
    clone = deepcopy(payload)
    for key in set(exclude):
        clone.pop(key, None)
    encoded = json.dumps(clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _decision_id(ev: Dict[str, Any]) -> str:
    payload = {
        "ticker": _clean_text(ev.get("ticker")).upper(),
        "decision_time": ev.get("decision_time"),
        "decision": ev.get("decision") or ev.get("decision_type"),
        "setup_type": ev.get("setup_type"),
        "main_blocker": ev.get("main_blocker"),
    }
    return _stable_hash(payload)[:24]


def _cycle_id(ev: Dict[str, Any]) -> str:
    dt = parse_time(ev.get("decision_time"))
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H")


def validation_blockers(ev: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if str(ev.get("label") or "") == "insufficient_evidence":
        blockers.append("insufficient_evidence_label")
    if not parse_time(ev.get("decision_time")):
        blockers.append("missing_decision_time")
    if not _clean_text(ev.get("ticker")):
        blockers.append("missing_ticker")
    required = [
        "future_window_hours",
        "max_favorable_excursion_pct",
        "max_adverse_excursion_pct",
        "estimated_roundtrip_fee_pct",
        "estimated_spread_cost_pct",
        "estimated_slippage_buffer_pct",
        "estimated_net_after_cost_opportunity_pct",
    ]
    for key in required:
        if ev.get(key) in (None, ""):
            blockers.append(f"missing_{key}")
    if not _clean_text(ev.get("reason") or ev.get("anti_hindsight_reason")):
        blockers.append("missing_anti_hindsight_reason")
    return sorted(set(blockers))


def normalize_reflection_evaluation(
    ev: Dict[str, Any],
    *,
    report: Optional[Dict[str, Any]] = None,
    evaluated_at: Optional[str] = None,
    market_intelligence_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    decision = _clean_text(ev.get("decision") or ev.get("decision_type"), "wait").lower()
    side = _clean_text(ev.get("side") or ev.get("side_bias"), "NONE").upper()
    if side == "BUY" and decision in {"wait", "watch", "skip", "no_trade", "reject", "hold"}:
        side = "NONE"
    label = _clean_text(ev.get("label"), "insufficient_evidence")
    blockers = validation_blockers(ev)
    raw_learning_context = ev.get("growbot_river_learning_context") if isinstance(ev.get("growbot_river_learning_context"), dict) else None
    learning_context = sanitize_learning_context_snapshot(raw_learning_context) if raw_learning_context else {}
    regime_context = {
        key: value
        for key, value in (learning_context.get("regime_context") or {}).items()
        if value not in (None, "", "unknown")
    }
    regime_source = {
        **ev,
        **regime_context,
        "adaptive_market_regime": learning_context.get("regime") if learning_context.get("regime") not in (None, "", "unknown") else ev.get("adaptive_market_regime"),
    }
    regime_fields = build_regime_enrichment_fields(
        regime_source,
        market_intelligence_context or (report or {}).get("market_intelligence_context"),
        ev.get("candle_context") if isinstance(ev.get("candle_context"), dict) else {},
    )
    normalized = {
        "schema_version": REFLECTION_SCHEMA_VERSION,
        "event_id": "",
        "decision_id": _decision_id(ev),
        "cycle_id": _cycle_id(ev),
        "decision_time": ev.get("decision_time"),
        "evaluated_at": evaluated_at or _clean_text((report or {}).get("generated_at"), now_iso()),
        "ticker": _clean_text(ev.get("ticker")).upper(),
        "setup_type": _clean_text(ev.get("setup_type"), "unknown"),
        "gate": _clean_text(ev.get("gate"), "analyze"),
        "decision": decision,
        "side": side,
        "confidence": ev.get("confidence", 0),
        "execution_status": _clean_text(ev.get("execution_status"), "no_trade"),
        "label": label,
        "main_blocker": _clean_text(ev.get("main_blocker")),
        "future_window_hours": int(_as_float(ev.get("future_window_hours"), 0)),
        "max_favorable_excursion_pct": _as_float(ev.get("max_favorable_excursion_pct")),
        "max_adverse_excursion_pct": _as_float(ev.get("max_adverse_excursion_pct")),
        "estimated_roundtrip_fee_pct": _as_float(ev.get("estimated_roundtrip_fee_pct")),
        "estimated_spread_cost_pct": _as_float(ev.get("estimated_spread_cost_pct")),
        "estimated_slippage_buffer_pct": _as_float(ev.get("estimated_slippage_buffer_pct")),
        "estimated_net_after_cost_opportunity_pct": _as_float(ev.get("estimated_net_after_cost_opportunity_pct")),
        "raw_market_regime": regime_fields["raw_market_regime"],
        "adaptive_market_regime": regime_fields["adaptive_market_regime"],
        "market_regime": regime_fields["market_regime"],
        "liquidity_regime": regime_fields["liquidity_regime"],
        "network_regime": regime_fields["network_regime"],
        "trend_regime": regime_fields["trend_regime"],
        "volatility_regime": regime_fields["volatility_regime"],
        "regime_source": regime_fields["regime_source"],
        "regime_key_design": regime_fields.get("regime_key_design", ""),
        "regime_enriched": regime_fields["regime_enriched"],
        "anti_hindsight_reason": _clean_text(ev.get("anti_hindsight_reason") or ev.get("reason")),
        "validated_conclusion": bool(is_validated_conclusion(ev)) and not blockers,
        "validation_blockers": blockers,
        "source_files": list(ev.get("source_files") or []),
        "source_hash": "",
        "created_by": CREATED_BY,
    }
    # Preserve historical event IDs when a source has no new context field.
    # Adding an empty key would make the append-only ledger treat all older
    # evaluations as new evidence on its next refresh.
    if raw_learning_context:
        normalized["growbot_river_learning_context"] = learning_context
    normalized["event_id"] = _stable_hash(normalized, exclude=RUNTIME_ONLY_FIELDS)
    normalized["source_hash"] = _stable_hash(
        {
            "phase": (report or {}).get("phase"),
            "generated_at": (report or {}).get("generated_at"),
            "evaluation": ev,
        },
        exclude={"generated_at"},
    )
    return normalized


def read_jsonl_ledger(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    corrupt = 0
    if not path.exists():
        return rows, corrupt
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            corrupt += 1
    return rows, corrupt


def append_reflection_evaluations(report: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, Any]:
    ledger_path = root / REFLECTION_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing, corrupt = read_jsonl_ledger(ledger_path)
    seen = {str(row.get("event_id")) for row in existing if row.get("event_id")}
    mi_context = (report.get("market_intelligence_context") if isinstance(report.get("market_intelligence_context"), dict) else None) or _load_json(root / "state/market_intelligence_context.json")
    normalized = [
        normalize_reflection_evaluation(ev, report=report, market_intelligence_context=mi_context)
        for ev in report.get("evaluations", [])
        if isinstance(ev, dict)
    ]
    new_rows = [row for row in normalized if row["event_id"] not in seen]
    if new_rows:
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return {
        "path": str(ledger_path),
        "input_evaluations": len(normalized),
        "appended_events": len(new_rows),
        "deduped_events": len(normalized) - len(new_rows),
        "existing_events": len(existing),
        "total_events": len(existing) + len(new_rows),
        "corrupt_lines": corrupt,
    }


def write_reflection_snapshots(report: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    generated = parse_time(report.get("generated_at")) or now_utc()
    stamp = generated.strftime("%Y%m%d-%H%M%S")
    json_path = root / REFLECTION_SNAPSHOT_DIR / f"reflection-learning-{stamp}.json"
    md_path = root / REFLECTION_SNAPSHOT_DIR / f"reflection-learning-{stamp}.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(json_path, report)
    md_path.write_text(render_report_markdown(report), encoding="utf-8")
    return {"snapshot_json": str(json_path), "snapshot_markdown": str(md_path)}


def load_reflection_events(root: Path = Path(".")) -> Tuple[List[Dict[str, Any]], int]:
    return read_jsonl_ledger(root / REFLECTION_LEDGER_PATH)


def _pressure_for_reflection(row: Dict[str, Any], *, candidate_hash: str = "") -> Optional[Dict[str, Any]]:
    label = str(row.get("label") or "")
    mapped = LABEL_PRESSURE_WEIGHTS.get(label)
    if not mapped:
        return None
    direction, weight = mapped
    quality = _conclusion_quality_score(row)
    score = round(float(weight) * float(quality), 6)
    loosen = score if direction == "loosen" else 0.0
    tighten = score if direction == "tighten" else 0.0
    parameter = map_pressure_to_parameter(row)
    scope = f"setup_type_specific:{row.get('setup_type') or 'unknown'}"
    regime_fields = build_regime_enrichment_fields(row)
    event = {
        "schema_version": PRESSURE_SCHEMA_VERSION,
        "event_id": "",
        "reflection_event_id": row.get("event_id"),
        "candidate_hash": candidate_hash,
        "parameter": parameter,
        "scope": scope,
        "direction": direction,
        "label": label,
        "label_weight": weight,
        "quality_score": round(quality, 6),
        "loosen_score": loosen,
        "tighten_score": tighten,
        "net_pressure": round(loosen - tighten, 6),
        "mapped_from_blocker": row.get("main_blocker") or "",
        "raw_market_regime": regime_fields["raw_market_regime"],
        "adaptive_market_regime": regime_fields["adaptive_market_regime"],
        "market_regime": regime_fields["market_regime"],
        "liquidity_regime": regime_fields["liquidity_regime"],
        "network_regime": regime_fields["network_regime"],
        "trend_regime": regime_fields["trend_regime"],
        "volatility_regime": regime_fields["volatility_regime"],
        "regime_source": regime_fields["regime_source"],
        "regime_key_design": regime_fields.get("regime_key_design", ""),
        "regime_enriched": regime_fields["regime_enriched"],
        "ticker": row.get("ticker") or "",
        "created_at": now_iso(),
    }
    event["event_id"] = _stable_hash(event, exclude={"event_id", "created_at"})
    return event


def append_parameter_pressure_events(
    reflection_events: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    root: Path = Path("."),
    candidate_hash: str = "",
) -> Dict[str, Any]:
    if reflection_events is None:
        reflection_events, corrupt_reflections = load_reflection_events(root)
    else:
        corrupt_reflections = 0
    ledger_path = root / PARAMETER_PRESSURE_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    existing, corrupt_pressure = read_jsonl_ledger(ledger_path)
    seen = {str(row.get("event_id")) for row in existing if row.get("event_id")}
    pressure_rows = [
        event
        for event in (_pressure_for_reflection(row, candidate_hash=candidate_hash) for row in reflection_events if row.get("validated_conclusion") is True)
        if event is not None
    ]
    new_rows = [row for row in pressure_rows if row["event_id"] not in seen]
    if new_rows:
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return {
        "path": str(ledger_path),
        "input_events": len(pressure_rows),
        "appended_events": len(new_rows),
        "deduped_events": len(pressure_rows) - len(new_rows),
        "existing_events": len(existing),
        "total_events": len(existing) + len(new_rows),
        "corrupt_lines": corrupt_pressure,
        "reflection_corrupt_lines": corrupt_reflections,
    }


def latest_snapshot(root: Path = Path(".")) -> str:
    snap_dir = root / REFLECTION_SNAPSHOT_DIR
    if not snap_dir.exists():
        return ""
    paths = sorted(snap_dir.glob("reflection-learning-*.json"))
    return str(paths[-1]) if paths else ""


def build_reflection_persistence_status(*, root: Path = Path(".")) -> Dict[str, Any]:
    reflection_rows, reflection_corrupt = load_reflection_events(root)
    pressure_rows, pressure_corrupt = read_jsonl_ledger(root / PARAMETER_PRESSURE_LEDGER_PATH)
    event_ids = [str(row.get("event_id")) for row in reflection_rows if row.get("event_id")]
    return {
        "reflection_ledger_available": (root / REFLECTION_LEDGER_PATH).exists(),
        "reflection_ledger_path": str(root / REFLECTION_LEDGER_PATH),
        "total_events": len(reflection_rows),
        "deduped_events": len(event_ids) - len(set(event_ids)),
        "validated_conclusions": sum(1 for row in reflection_rows if row.get("validated_conclusion") is True),
        "corrupt_lines": reflection_corrupt,
        "latest_snapshot": latest_snapshot(root),
        "parameter_pressure_ledger_available": (root / PARAMETER_PRESSURE_LEDGER_PATH).exists(),
        "parameter_pressure_ledger_path": str(root / PARAMETER_PRESSURE_LEDGER_PATH),
        "parameter_pressure_events": len(pressure_rows),
        "parameter_pressure_corrupt_lines": pressure_corrupt,
        "candidate_analysis_available": (root / "reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.json").exists(),
        "can_authorize_execution": False,
        "can_mutate_parameters": False,
        "source_policy": SOURCE_POLICY,
    }


def render_persistence_audit(status: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Reflection Persistence Audit",
            "",
            f"Reflection ledger: {status.get('reflection_ledger_path')}",
            f"Total events: {status.get('total_events')}",
            f"Validated conclusions: {status.get('validated_conclusions')}",
            f"Corrupt lines: {status.get('corrupt_lines')}",
            f"Parameter pressure events: {status.get('parameter_pressure_events')}",
            "",
            "## Safety",
            "- can_authorize_execution: false",
            "- can_mutate_parameters: false",
            "- no Coinbase submit/cancel/replace calls",
            "- no .env mutation",
            "- no production order-state mutation",
        ]
    ) + "\n"


def write_reflection_persistence_audit(*, root: Path = Path(".")) -> Dict[str, Any]:
    status = build_reflection_persistence_status(root=root)
    audit = {
        "generated_at": now_iso(),
        "status": status,
        "safety_policy": {
            "no_coinbase_actions": True,
            "no_env_mutation": True,
            "no_production_order_state_mutation": True,
            "no_approved_profile_mutation": True,
        },
        "can_authorize_execution": False,
        "can_mutate_parameters": False,
    }
    json_path = root / "reports/audits/reflection-persistence-latest.json"
    md_path = root / "reports/audits/reflection-persistence-latest.md"
    atomic_write_json(json_path, audit)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_persistence_audit(status), encoding="utf-8")
    audit["outputs"] = {"json": str(json_path), "markdown": str(md_path)}
    return audit


__all__ = [
    "PARAMETER_PRESSURE_LEDGER_PATH",
    "REFLECTION_LEDGER_PATH",
    "append_parameter_pressure_events",
    "append_reflection_evaluations",
    "build_reflection_persistence_status",
    "load_reflection_events",
    "normalize_reflection_evaluation",
    "read_jsonl_ledger",
    "write_reflection_persistence_audit",
    "write_reflection_snapshots",
]
