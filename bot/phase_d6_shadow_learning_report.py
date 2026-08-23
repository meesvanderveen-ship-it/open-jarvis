from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


PHASE_D6_SHADOW_LEARNING_REPORT = "d6_shadow_learning_report_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _source(root: Path, rel: str) -> Dict[str, Any]:
    path = root / rel
    payload = _load_json(path)
    return {
        "path": str(path),
        "available": bool(payload),
        "phase": payload.get("phase"),
        "classification": payload.get("classification"),
    }


def build_d6_shadow_learning_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    label_pack = _load_json(project_root / "reports/d6/d6-backlearning-label-export-pack-20260609.json")
    label_counts = label_pack.get("label_counts") if isinstance(label_pack.get("label_counts"), dict) else {}
    sources = {
        "label_export_pack": _source(project_root, "reports/d6/d6-backlearning-label-export-pack-20260609.json"),
        "acceptance_policy": _source(project_root, "reports/d6/d6-acceptance-policy-20260609.json"),
        "human_review_decision_pack": _source(project_root, "reports/d6/d6-human-review-decision-pack-20260609.json"),
        "controlled_learning_governance": _source(project_root, "reports/d6/controlled-learning-governance-20260609.json"),
        "multi_ticker_paper_replay": _source(project_root, "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json"),
        "product_rule_fixture_evidence": _source(project_root, "reports/d6/product-rule-fixture-evidence-20260609.json"),
    }
    missing = [key for key, value in sources.items() if not value["available"]]
    classification = "WATCH" if missing else "OK"
    report = {
        "phase": PHASE_D6_SHADOW_LEARNING_REPORT,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "dry_run_only": True,
            "shadow_learning_only": True,
            "execution_bridge_created": False,
            "runtime_coupling_created": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_proposed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
        },
        "classification": classification,
        "label_sources_used": sources,
        "missing_label_sources": missing,
        "learning_inputs": [
            "ticker labels",
            "paper lifecycle labels",
            "outcome labels",
            "review labels",
            "governance labels",
            "product-rule evidence classes",
            "D5/D6 fee/no-fill/cancel-replace labels",
        ],
        "label_counts": {
            "ticker_label_count": int(label_counts.get("ticker_label_count") or 0),
            "lifecycle_label_count": int(label_counts.get("lifecycle_label_count") or 0),
            "outcome_label_count": int(label_counts.get("outcome_label_count") or 0),
            "review_label_count": int(label_counts.get("review_label_count") or 0),
            "governance_label_count": int(label_counts.get("governance_label_count") or 0),
            "export_record_count": int(label_counts.get("export_record_count") or 0),
        },
        "allowed_shadow_outputs": [
            "offline label completeness summaries",
            "evidence sufficiency ledgers",
            "non-executable diagnostics",
            "human-review queue suggestions without ranking live strategies",
            "schema validation warnings",
        ],
        "forbidden_outputs": [
            "parameter values",
            "strategy rankings for live use",
            "runtime configuration changes",
            "order instructions",
            "execution bridge artifacts",
            "live-learning enablement",
        ],
        "isolation_boundaries": [
            "read local reports only",
            "write reports/d6 artifacts only",
            "do not import runtime trader loop for decisions",
            "do not write state/",
            "do not write config, prompts, risk settings or parameters",
            "do not call Coinbase, market-data or HTTP endpoints",
        ],
        "rollback_requirements": [
            "shadow outputs must be discardable",
            "no runtime dependency may point at shadow outputs",
            "future bridge requires separate exact ACK and revert plan",
        ],
        "review_requirements": [
            "human review before parameter-review candidate promotion",
            "acceptance policy sufficiency ledger",
            "selected safe regression harness pass",
            "explicit ACK before any parameter proposal/change",
        ],
        "next_safe_stage": "policy_sufficiency_ledger_report_only",
        "blockers_to_execution_bridge": [
            "parameter_review_candidate=false",
            "parameter_proposal_candidate=false",
            "parameter_change_allowed=false",
            "learning_to_execution_ready=false",
            "live_learning_allowed=false",
            "exact execution-bridge ACK missing",
        ],
        "governance_flags": {
            "d6_shadow_learning_report_ready": True,
            "report_only_shadow_learning_ready": True,
            "dry_run_shadow_learning_allowed": True,
            "execution_bridge_created": False,
            "runtime_coupling_created": False,
            "parameter_values_proposed": False,
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
    }
    return _json_safe(report)


def render_d6_shadow_learning_report_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# D6 Shadow Learning Report",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- dry_run_only: `{meta.get('dry_run_only')}`",
        f"- execution_bridge_created: `{meta.get('execution_bridge_created')}`",
        f"- runtime_coupling_created: `{meta.get('runtime_coupling_created')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- learning_to_execution_ready: `{meta.get('learning_to_execution_ready')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Isolation Boundaries", ""])
    for item in report.get("isolation_boundaries") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Blockers To Execution Bridge", ""])
    for item in report.get("blockers_to_execution_bridge") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_D6_SHADOW_LEARNING_REPORT",
    "build_d6_shadow_learning_report",
    "render_d6_shadow_learning_report_markdown",
]
