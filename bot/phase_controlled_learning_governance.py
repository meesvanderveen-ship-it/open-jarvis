from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_CONTROLLED_LEARNING_GOVERNANCE = "controlled_learning_governance_v1"


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


def _stage(
    *,
    stage: int,
    name: str,
    current_status: str,
    required_inputs: List[str],
    blockers: List[str],
    allowed_next_action: str,
    forbidden_actions: List[str],
    requires_ACK: bool,
    evidence_artifacts_required: List[str],
    test_artifacts_required: List[str],
    rollback_or_revert_requirement: str,
) -> Dict[str, Any]:
    return {
        "stage": stage,
        "name": name,
        "current_status": current_status,
        "required_inputs": required_inputs,
        "blockers": blockers,
        "allowed_next_action": allowed_next_action,
        "forbidden_actions": forbidden_actions,
        "requires_ACK": requires_ACK,
        "evidence_artifacts_required": evidence_artifacts_required,
        "test_artifacts_required": test_artifacts_required,
        "rollback_or_revert_requirement": rollback_or_revert_requirement,
        "parameter_values_proposed": False,
        "parameter_mutation_performed": False,
        "learning_to_execution_ready": False,
        "live_learning_allowed": False,
    }


def build_controlled_learning_governance_report(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    sources = {
        "acceptance_policy": _source(project_root, "reports/d6/d6-acceptance-policy-20260609.json"),
        "label_export_pack": _source(project_root, "reports/d6/d6-backlearning-label-export-pack-20260609.json"),
        "human_review_decision_pack": _source(project_root, "reports/d6/d6-human-review-decision-pack-20260609.json"),
        "parameter_evidence_plan": _source(project_root, "reports/d6/d6-backlearning-parameter-evidence-plan-20260609.json"),
        "roadmap_decision_map": _source(project_root, "reports/d6/roadmap-readiness-decision-map-20260609.json"),
        "safe_regression_harness": _source(project_root, "reports/d6/safe-regression-harness-20260609.json"),
    }
    missing_sources = [key for key, value in sources.items() if not value["available"]]

    stages = [
        _stage(
            stage=0,
            name="evidence_collection_only",
            current_status="ready",
            required_inputs=["local reports", "local fixtures", "read-only evidence labels"],
            blockers=[],
            allowed_next_action="Continue local evidence collection and report-only label production.",
            forbidden_actions=["live trading", "parameter mutation", "learning-to-execution"],
            requires_ACK=False,
            evidence_artifacts_required=["D5/D6 evidence reports", "paper replay reports"],
            test_artifacts_required=["focused report-only tests"],
            rollback_or_revert_requirement="No runtime rollback required because no state or parameter mutation is allowed.",
        ),
        _stage(
            stage=1,
            name="label_export_ready",
            current_status="ready" if sources["label_export_pack"]["available"] else "blocked",
            required_inputs=["D6 backlearning label export pack"],
            blockers=[] if sources["label_export_pack"]["available"] else ["label export pack missing"],
            allowed_next_action="Use labels for offline human review only.",
            forbidden_actions=["train live model", "rank strategies for live use", "mutate parameters"],
            requires_ACK=False,
            evidence_artifacts_required=["reports/d6/d6-backlearning-label-export-pack-20260609.json"],
            test_artifacts_required=["tests/test_phase_d6_backlearning_label_export_pack.py"],
            rollback_or_revert_requirement="Discard exported labels if schema or evidence source is later rejected.",
        ),
        _stage(
            stage=2,
            name="human_review_ready",
            current_status="ready" if sources["human_review_decision_pack"]["available"] else "blocked",
            required_inputs=["human-review decision pack", "evidence area classifications"],
            blockers=[] if sources["human_review_decision_pack"]["available"] else ["human-review decision pack missing"],
            allowed_next_action="Review evidence classifications without changing parameters.",
            forbidden_actions=["approve parameter changes", "propose live parameter values", "enable learning"],
            requires_ACK=False,
            evidence_artifacts_required=["reports/d6/d6-human-review-decision-pack-20260609.json"],
            test_artifacts_required=["tests/test_phase_d6_human_review_decision_pack.py"],
            rollback_or_revert_requirement="Rebuild decision pack if evidence inputs change.",
        ),
        _stage(
            stage=3,
            name="acceptance_policy_ready",
            current_status="ready" if sources["acceptance_policy"]["available"] else "blocked",
            required_inputs=["sample-size policy", "OOS policy", "walk-forward policy"],
            blockers=[] if sources["acceptance_policy"]["available"] else ["D6 acceptance policy missing"],
            allowed_next_action="Apply the policy as a report-only sufficiency checklist.",
            forbidden_actions=["optimize", "rank parameter values", "approve parameter review"],
            requires_ACK=False,
            evidence_artifacts_required=["reports/d6/d6-acceptance-policy-20260609.json"],
            test_artifacts_required=["tests/test_phase_d6_acceptance_policy.py"],
            rollback_or_revert_requirement="Revise policy text/report before any future review candidate decision.",
        ),
        _stage(
            stage=4,
            name="parameter_review_candidate",
            current_status="blocked",
            required_inputs=["policy pass/fail ledger", "sample-size/OOS/walk-forward evidence", "human review acceptance"],
            blockers=["parameter_review_candidate=false", "sample-size/OOS/walk-forward ledger not accepted"],
            allowed_next_action="Build a report-only evidence ledger against the acceptance policy.",
            forbidden_actions=["propose parameter values", "change config", "connect learning to execution"],
            requires_ACK=True,
            evidence_artifacts_required=["accepted human-review record", "policy sufficiency ledger"],
            test_artifacts_required=["selected safe regression harness"],
            rollback_or_revert_requirement="Any future candidate decision must be reversible by report withdrawal before config edits.",
        ),
        _stage(
            stage=5,
            name="parameter_proposal_candidate",
            current_status="blocked",
            required_inputs=["parameter_review_candidate=true", "explicit proposal authorization"],
            blockers=["parameter_review_candidate=false", "parameter_values_proposed=false"],
            allowed_next_action="None in this sprint; wait for explicit ACK and separate prompt.",
            forbidden_actions=["propose parameter values", "optimize", "rank strategies"],
            requires_ACK=True,
            evidence_artifacts_required=["accepted parameter-review candidate pack"],
            test_artifacts_required=["proposal-specific tests after future ACK"],
            rollback_or_revert_requirement="Future proposal must include exact revert path before any parameter edit.",
        ),
        _stage(
            stage=6,
            name="human_parameter_approval_required",
            current_status="blocked_by_ACK",
            required_inputs=["parameter proposal pack", "human approval", "exact ACK"],
            blockers=["no parameter proposal exists", "parameter_review_approved=false"],
            allowed_next_action="No action now; approval remains a future ACK-gated step.",
            forbidden_actions=["approve parameters implicitly", "mutate parameters"],
            requires_ACK=True,
            evidence_artifacts_required=["signed/recorded human approval pack"],
            test_artifacts_required=["pre-change validation pack"],
            rollback_or_revert_requirement="Approved change must include explicit before/after diff and revert command.",
        ),
        _stage(
            stage=7,
            name="dry_run_shadow_learning_allowed",
            current_status="blocked",
            required_inputs=["approved report-only shadow design", "no execution bridge", "no parameter mutation"],
            blockers=["dry_run_shadow_learning_allowed=false", "shadow learning design not requested"],
            allowed_next_action="Design a dry-run shadow-learning report only if requested; do not execute learning.",
            forbidden_actions=["write learned parameters", "drive runtime decisions", "enable live learning"],
            requires_ACK=True,
            evidence_artifacts_required=["shadow-learning governance design"],
            test_artifacts_required=["dry-run no-mutation tests"],
            rollback_or_revert_requirement="Shadow outputs must be discardable and isolated from runtime config.",
        ),
        _stage(
            stage=8,
            name="execution_bridge_candidate",
            current_status="blocked",
            required_inputs=["approved parameter changes", "shadow evidence", "explicit execution bridge ACK"],
            blockers=["learning_to_execution_ready=false", "no execution bridge approved"],
            allowed_next_action="None; keep execution bridge absent.",
            forbidden_actions=["connect learning outputs to orders", "mutate runtime thresholds"],
            requires_ACK=True,
            evidence_artifacts_required=["approved shadow-learning evidence"],
            test_artifacts_required=["execution bridge safety tests after future ACK"],
            rollback_or_revert_requirement="Future bridge must have kill switch and exact revert.",
        ),
        _stage(
            stage=9,
            name="live_learning_candidate",
            current_status="blocked",
            required_inputs=["execution bridge candidate", "live-learning governance approval"],
            blockers=["live_learning_allowed=false", "execution_bridge_candidate=false"],
            allowed_next_action="None; live-learning remains forbidden.",
            forbidden_actions=["enable live learning", "rank strategies for live deployment"],
            requires_ACK=True,
            evidence_artifacts_required=["live-learning governance pack"],
            test_artifacts_required=["live-learning preflight tests after future ACK"],
            rollback_or_revert_requirement="Future live-learning candidate must include service-disable and parameter rollback plan.",
        ),
        _stage(
            stage=10,
            name="live_learning_allowed",
            current_status="blocked",
            required_inputs=["live-learning candidate", "operator exact ACK", "all safety gates passed"],
            blockers=["live_learning_allowed=false", "no exact ACK", "learning_to_execution_ready=false"],
            allowed_next_action="None.",
            forbidden_actions=["enable live learning", "start live trading from learning outputs"],
            requires_ACK=True,
            evidence_artifacts_required=["final live-learning authorization pack"],
            test_artifacts_required=["full ACK-gated live-learning preflight"],
            rollback_or_revert_requirement="Immediate disable path and parameter rollback required before any future authorization.",
        ),
    ]

    ready_stage_count = sum(1 for row in stages if row["current_status"] == "ready")
    blocked_stage_count = sum(1 for row in stages if row["current_status"] in {"blocked", "blocked_by_ACK"})
    stage_by_name = {row["name"]: row for row in stages}
    current_max_allowed_stage = (
        "acceptance_policy_ready"
        if all(stage_by_name[name]["current_status"] == "ready" for name in ("evidence_collection_only", "label_export_ready", "human_review_ready", "acceptance_policy_ready"))
        else "evidence_collection_only"
    )

    report = {
        "phase": PHASE_CONTROLLED_LEARNING_GOVERNANCE,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "governance_only": True,
            "no_execution_bridge": True,
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
        "classification": "WATCH",
        "evidence_sources": sources,
        "missing_evidence_sources": missing_sources,
        "stage_matrix": stages,
        "blocked_stage_count": blocked_stage_count,
        "ready_stage_count": ready_stage_count,
        "current_max_allowed_stage": current_max_allowed_stage,
        "next_safe_stage": "policy_sufficiency_ledger_report_only",
        "explicit_ACK_requirements": [
            "parameter_review_candidate promotion",
            "parameter proposal creation",
            "parameter approval or config mutation",
            "dry-run shadow learning design if it could influence runtime",
            "execution bridge",
            "live learning",
        ],
        "forbidden_transitions": [
            "label_export_ready -> parameter_proposal_candidate",
            "human_review_ready -> parameter_change_allowed",
            "acceptance_policy_ready -> learning_to_execution",
            "parameter_review_candidate -> live_learning_allowed",
            "dry_run_shadow_learning_allowed -> execution_bridge without exact ACK",
        ],
        "recommended_next_actions": [
            "Build a report-only policy sufficiency ledger if the operator wants to progress parameter-review candidacy.",
            "Keep learning outputs disconnected from runtime execution.",
            "Use selected safe regression harness before any future governance change.",
        ],
        "governance_flags": {
            "controlled_learning_governance_ready": True,
            "current_max_allowed_learning_stage": current_max_allowed_stage,
            "evidence_collection_only": True,
            "label_export_ready": stage_by_name["label_export_ready"]["current_status"] == "ready",
            "human_review_ready": stage_by_name["human_review_ready"]["current_status"] == "ready",
            "acceptance_policy_ready": stage_by_name["acceptance_policy_ready"]["current_status"] == "ready",
            "parameter_review_candidate": False,
            "parameter_proposal_candidate": False,
            "parameter_values_proposed": False,
            "parameter_review_approved": False,
            "parameter_change_allowed": False,
            "dry_run_shadow_learning_allowed": False,
            "execution_bridge_candidate": False,
            "learning_to_execution_ready": False,
            "live_learning_candidate": False,
            "live_learning_allowed": False,
        },
        "does_not_authorize_live_trading": True,
        "does_not_authorize_parameter_changes": True,
    }
    return _json_safe(report)


def render_controlled_learning_governance_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# Controlled Learning Governance",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- no_execution_bridge: `{meta.get('no_execution_bridge')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_ready: `{meta.get('learning_to_execution_ready')}`",
        f"- live_learning_allowed: `{meta.get('live_learning_allowed')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Stages", ""])
    for row in report.get("stage_matrix") or []:
        lines.append(
            f"- {row.get('stage')}. {row.get('name')}: status=`{row.get('current_status')}`, "
            f"requires_ACK=`{row.get('requires_ACK')}`, allowed_next_action=`{row.get('allowed_next_action')}`"
        )
    lines.extend(["", "## Forbidden Transitions", ""])
    for transition in report.get("forbidden_transitions") or []:
        lines.append(f"- {transition}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_CONTROLLED_LEARNING_GOVERNANCE",
    "build_controlled_learning_governance_report",
    "render_controlled_learning_governance_markdown",
]
