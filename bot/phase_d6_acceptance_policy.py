from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_D6_ACCEPTANCE_POLICY = "d6_acceptance_policy_v1"

POLICY_SECTIONS = [
    "sample_size_policy",
    "oos_policy",
    "walk_forward_policy",
    "fill_realism_policy",
    "product_rule_policy",
    "human_review_policy",
    "parameter_review_gate_policy",
    "live_learning_gate_policy",
]


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


def _source(root: Path, key: str, rel: str) -> Dict[str, Any]:
    path = root / rel
    payload = _load_json(path)
    if not path.exists():
        return {"key": key, "path": str(path), "available": False, "reason": "missing_optional_source"}
    if not payload:
        return {"key": key, "path": str(path), "available": False, "reason": "malformed_or_empty_json"}
    return {
        "key": key,
        "path": str(path),
        "available": True,
        "classification": payload.get("classification", payload.get("status")),
        "phase": payload.get("phase"),
    }


def _evidence_sources(root: Path) -> List[Dict[str, Any]]:
    return [
        _source(root, "multi_ticker_paper_lifecycle_replay", "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json"),
        _source(root, "product_rule_fixture_evidence", "reports/d6/product-rule-fixture-evidence-20260609.json"),
        _source(root, "per_ticker_product_rule_evidence_cache", "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json"),
        _source(root, "d6_human_review_decision_pack", "reports/d6/d6-human-review-decision-pack-20260609.json"),
        _source(root, "d6_backlearning_parameter_evidence_plan", "reports/d6/d6-backlearning-parameter-evidence-plan-20260609.json"),
        _source(root, "d5_d6_evidence_expansion", "reports/d6/d5-d6-evidence-expansion-20260609.json"),
        _source(root, "all_ticker_readiness_gate", "reports/d6/all-ticker-readiness-gate-20260609.json"),
        _source(root, "safe_regression_harness", "reports/d6/safe-regression-harness-20260609.json"),
    ]


def _policy_row(
    *,
    name: str,
    purpose: str,
    rules: List[str],
    current_evidence: List[str],
    blockers: List[str],
    allowed_next_action: str,
    forbidden_actions: List[str],
) -> Dict[str, Any]:
    return {
        "policy": name,
        "purpose": purpose,
        "rules": rules,
        "current_evidence": current_evidence,
        "blockers": blockers,
        "allowed_next_action": allowed_next_action,
        "forbidden_actions": forbidden_actions,
        "policy_passed": False,
        "parameter_review_candidate": False,
        "parameter_values_proposed": False,
        "parameter_change_allowed": False,
        "learning_to_execution_ready": False,
    }


def _policy_sections() -> Dict[str, Dict[str, Any]]:
    return {
        "sample_size_policy": _policy_row(
            name="sample_size_policy",
            purpose="Define minimum human-review evidence counts before parameter review can become a candidate.",
            rules=[
                "Require reviewed samples per ticker before ticker-specific parameter review.",
                "Require reviewed samples per setup type before setup-specific parameter review.",
                "Require reviewed samples per decision type: approve, wait, reject, reduce and close.",
                "Require lifecycle outcome coverage across no-fill, fill, partial-fill, cancel/replace and fee evidence.",
                "Treat current counts as labels for planning only, not as sufficient sample-size proof.",
            ],
            current_evidence=[
                "18 configured tickers have paper lifecycle replay labels.",
                "D5/D6 evidence expansion records fee gap, no-fill and cancel/replace labels.",
            ],
            blockers=[
                "No accepted minimum sample-size threshold has been approved.",
                "Current non-BTC evidence is paper/fixture-only.",
                "No OOS/walk-forward reviewed sample ledger exists.",
            ],
            allowed_next_action="Build a sample ledger and count labels by ticker, setup, decision and lifecycle outcome.",
            forbidden_actions=[
                "propose parameter values",
                "change thresholds",
                "rank strategies for live use",
                "enable learning-to-execution",
            ],
        ),
        "oos_policy": _policy_row(
            name="oos_policy",
            purpose="Prevent lookahead, leakage and in-sample-only review from approving parameter review.",
            rules=[
                "Require explicit train/test split before any parameter review candidate.",
                "Require no-lookahead and no-leakage checks for every evidence set.",
                "Require OOS results to be reported separately from exploratory labels.",
                "Require evidence staleness review before live-scope use.",
            ],
            current_evidence=["D6 historical/backtest scaffolds exist locally.", "Current sprint did not run optimization or fetch data."],
            blockers=["No current OOS acceptance report covers the new all-ticker paper label set."],
            allowed_next_action="Create report-only OOS acceptance criteria and label lineage checks.",
            forbidden_actions=["optimize parameters", "rank OOS variants for live use", "mutate config"],
        ),
        "walk_forward_policy": _policy_row(
            name="walk_forward_policy",
            purpose="Define walk-forward evidence requirements before parameter review can be considered.",
            rules=[
                "Require multiple chronological windows.",
                "Require window-level pass/fail summaries.",
                "Require degradation and stability review across windows.",
                "Treat stale or fixture-only evidence as planning evidence only.",
            ],
            current_evidence=["Walk-forward helper modules exist locally.", "Paper lifecycle labels can be exported for future review."],
            blockers=["No current walk-forward decision report has accepted the new label pack."],
            allowed_next_action="Produce a walk-forward acceptance checklist without running optimization.",
            forbidden_actions=["select best parameters", "change live parameters", "enable live learning"],
        ),
        "fill_realism_policy": _policy_row(
            name="fill_realism_policy",
            purpose="Keep maker/post-only, no-fill, partial-fill, cancel/replace, fee and slippage assumptions reviewable.",
            rules=[
                "Require post-only/maker assumptions to be explicit.",
                "Require no-fill duration labels and terminal state evidence.",
                "Require partial-fill handling evidence before automation.",
                "Require fee/slippage assumptions to include known TP_CLOSE fee discrepancy.",
            ],
            current_evidence=[
                "D5/D6 evidence expansion records no-fill and cancel/replace evidence.",
                "TP_CLOSE fee gap is accepted for human review only.",
            ],
            blockers=["Partial-fill evidence is absent.", "Fee discrepancy is unresolved for parameter review."],
            allowed_next_action="Export fill/no-fill/cancel/replace/fee labels for human review.",
            forbidden_actions=["change timeouts", "change cancel/replace timing", "automate partial-fill handling"],
        ),
        "product_rule_policy": _policy_row(
            name="product_rule_policy",
            purpose="Separate paper fixture evidence from live product-rule proof.",
            rules=[
                "BTC-USDC live-readonly cached evidence can support paper review but still needs fresh preflight.",
                "Non-BTC local_fixture evidence supports paper replay only.",
                "All live scope requires fresh Coinbase product-rule preflight and exact ACK.",
                "Fixture evidence cannot authorize all-ticker live.",
            ],
            current_evidence=[
                "product_rule_fixture_evidence_ready=true",
                "paper_replay_usable_ticker_count=18",
                "strong_live_or_cached_evidence_count=1",
            ],
            blockers=["17 non-BTC tickers lack strong live/cached product-rule evidence."],
            allowed_next_action="Use fixtures for paper labels and require ACK-gated live-readonly product-rule design later.",
            forbidden_actions=["fetch Coinbase product rules without ACK", "mark non-BTC live-ready from fixtures"],
        ),
        "human_review_policy": _policy_row(
            name="human_review_policy",
            purpose="Define review statuses and keep labels separate from approvals.",
            rules=[
                "Classify areas as accepted_for_human_review, labels_only, insufficient, blocked or out_of_scope_until_ACK.",
                "Labels-only evidence may feed export packs but not parameter changes.",
                "Blocked evidence must remain blocked until its exact prerequisite is cleared.",
            ],
            current_evidence=["D6 human-review decision pack classifies 12 evidence areas."],
            blockers=["Several areas require more local evidence or are blocked."],
            allowed_next_action="Use decision-pack statuses as export labels.",
            forbidden_actions=["approve parameter review", "approve live learning", "approve all-ticker live"],
        ),
        "parameter_review_gate_policy": _policy_row(
            name="parameter_review_gate_policy",
            purpose="Keep parameter review candidate false until all policy areas pass.",
            rules=[
                "parameter_review_candidate remains false unless sample-size, OOS, walk-forward, fill realism, product-rule and human-review policies pass.",
                "parameter_review_approved remains false until separate human approval.",
                "parameter_change_allowed remains false until separate exact ACK.",
            ],
            current_evidence=["Current decision pack sets parameter_review_candidate=false."],
            blockers=["Policy is defined but not passed by current evidence."],
            allowed_next_action="Build label export and evidence ledgers for future human review.",
            forbidden_actions=["propose parameter values", "mutate parameters", "enable execution bridge"],
        ),
        "live_learning_gate_policy": _policy_row(
            name="live_learning_gate_policy",
            purpose="Block live learning and learning-to-execution until separate governance exists.",
            rules=[
                "learning_to_execution_ready remains false.",
                "live_learning_allowed remains false.",
                "Any future bridge requires separate governance, exact ACK and safety review.",
            ],
            current_evidence=["All recent D6 reports keep learning-to-execution false."],
            blockers=["No live-learning governance design has been approved."],
            allowed_next_action="Design governance only, with no execution bridge.",
            forbidden_actions=["enable live learning", "connect backlearning outputs to execution", "change runtime parameters"],
        ),
    }


def build_d6_acceptance_policy_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    evidence_sources = _evidence_sources(project_root)
    missing = [row for row in evidence_sources if not row.get("available")]
    sections = _policy_sections()
    watch_reasons = [
        "policy_defined_not_passed",
        "parameter_review_candidate_false",
        "sample_size_oos_walk_forward_evidence_incomplete",
    ]
    if missing:
        watch_reasons.append("optional_evidence_sources_missing_or_malformed")
    report = {
        "phase": PHASE_D6_ACCEPTANCE_POLICY,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "policy_only": True,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_proposed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_ready": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
        },
        "classification": "WATCH",
        "watch_reasons": sorted(set(watch_reasons)),
        "stop_reasons": [],
        "evidence_sources_inspected": evidence_sources,
        "policy_sections": sections,
        **sections,
        "governance_flags": {
            "d6_acceptance_policy_ready": True,
            "parameter_review_candidate": False,
            "parameter_values_proposed": False,
            "parameter_review_approved": False,
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
        "recommended_next_steps": [
            "D6 backlearning label export pack",
            "readiness decision map",
            "future OOS/walk-forward evidence ledger without optimization",
        ],
    }
    return _json_safe(report)


def render_d6_acceptance_policy_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# D6 Acceptance Policy",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- policy_only: `{meta.get('policy_only')}`",
        f"- optimization_performed: `{meta.get('optimization_performed')}`",
        f"- ranking_performed: `{meta.get('ranking_performed')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_ready: `{meta.get('learning_to_execution_ready')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Policy Sections", ""])
    for name in POLICY_SECTIONS:
        section = report.get(name) or {}
        lines.append(f"### {name}")
        lines.append(f"- purpose: `{section.get('purpose')}`")
        lines.append(f"- policy_passed: `{section.get('policy_passed')}`")
        lines.append(f"- allowed_next_action: `{section.get('allowed_next_action')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_D6_ACCEPTANCE_POLICY",
    "build_d6_acceptance_policy_report",
    "render_d6_acceptance_policy_markdown",
]
