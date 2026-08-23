from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_UNRESOLVED_BLOCKER_LEDGER = "unresolved_blocker_ledger_v1"


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


def _item(category: str, item: str, blocker_type: str, why: str, done_when: str, blocks_btc: bool, blocks_full: bool) -> Dict[str, Any]:
    return {
        "category": category,
        "item": item,
        "blocker_type": blocker_type,
        "why_it_remains": why,
        "done_when": done_when,
        "codex_can_build_more_now_without_ack_live_external_code": blocker_type == "locally_buildable",
        "blocks_operator_started_BTC_USDC_24h_test": blocks_btc,
        "blocks_full_workflow": blocks_full,
    }


def build_unresolved_blocker_ledger(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    shadow = _load_json(project_root / "reports/d6/d6-shadow-learning-report-20260609.json")
    checklist = _load_json(project_root / "reports/d6/operator-24h-prerun-build-checklist-20260609.json")
    all_ticker_pack = _load_json(project_root / "reports/d6/all-ticker-24h-workflow-readiness-pack-20260609.json")
    all_ticker_commands = _load_json(project_root / "reports/d6/all-ticker-operator-preflight-command-pack-20260609.json")
    all_ticker_guard = _load_json(project_root / "reports/d6/all-ticker-live-scope-guard-20260609.json")
    all_ticker_preflight = _load_json(project_root / "reports/d6/all-ticker-live-readonly-preflight-20260609.json")
    shadow_params = _load_json(project_root / "reports/d6/shadow-parameter-approximation-pack-20260609.json")
    items: List[Dict[str, Any]] = [
        _item("BTC-USDC live start", "fresh preflight and live-start ACK", "blocked_by_ACK", "Codex must not call Coinbase or start the 24h run without exact scoped ACK.", "operator explicitly requests fresh preflight/decision pack and later starts manually", True, True),
        _item("master BUY lifecycle", "live BUY proof for new run", "blocked_by_live_fresh_preflight", "Local build artifacts are present; live proof requires fresh preflight and operator action.", "operator-run evidence is collected and post-run pack is built", True, True),
        _item("master SELL/exit lifecycle", "live position/fill and D2/D3 evidence", "blocked_by_live_position_fill_evidence", "No open live position or D3 exit exists; live SELL requires separate evidence and ACK.", "a live fill/position exists and D2/D3 preview plus ACK are present", False, True),
        _item("all-ticker lifecycle/live parity", "non-BTC live product-rule and lifecycle proof", "blocked_by_live_fresh_preflight", "Non-BTC evidence is fixture/paper only and all-ticker live remains disabled.", "fresh live-readonly evidence and per-ticker lifecycle proof exist with ACK", False, True),
        _item("D6/backlearning/governance", "policy sufficiency ledger acceptance", "blocked_by_ACK", "Report-only governance exists; candidate promotion requires human review and ACK.", "human review accepts a sufficiency ledger", False, True),
        _item("shadow learning", "execution bridge", "blocked_by_ACK", "Shadow learning is report-only and isolated; execution bridge is forbidden.", "separate exact ACK plus bridge design/tests/revert plan", False, True),
        _item("parameter review/change", "parameter proposal/change", "blocked_by_ACK", "Parameter proposals and changes are intentionally forbidden.", "separate ACK authorizes proposal, approval and exact before/after diff", False, True),
        _item("follower/replication", "receiver/API implementation audit", "blocked_by_external_follower_repo", "Follower receiver/API code is not accessible locally.", "operator provides repo/path and local static audit passes", False, True),
        _item("state hygiene cleanup", "stale reserved_base denormalized field apply", "blocked_by_ACK", "Preview exists, but state writes require exact cleanup ACK.", "operator provides exact cleanup apply ACK and fresh hashes", False, False),
        _item("regression/operator workflow", "selected harness and final build checklist", "locally_complete", "Local selected harness and checklist exist; no live authorization implied.", "already complete unless new local tooling is added", False, False),
        _item("docs/runbook completeness", "local build closure checkpoint", "locally_complete", "Docs can be kept current; live instructions remain ACK-gated.", "current sprint checkpoint is recorded", False, False),
    ]
    if all_ticker_pack:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker 24h workflow readiness pack",
                "locally_complete",
                "Local all-ticker workflow pack exists, but live preflight/ACK remain blocked.",
                "fresh all-ticker live-readonly preflight and exact ACK exist",
                False,
                True,
            )
        )
    else:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker 24h workflow readiness pack",
                "locally_buildable",
                "All-ticker local decision pack has not been generated yet.",
                "all-ticker workflow readiness artifact exists and live authorization remains false",
                False,
                False,
            )
        )
    if all_ticker_commands:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker operator preflight command templates",
                "locally_complete",
                "Operator-only command templates exist and are not executed by Codex.",
                "already complete unless command templates change",
                False,
                False,
            )
        )
    else:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker operator preflight command templates",
                "locally_buildable",
                "Operator-only all-ticker command pack has not been generated yet.",
                "command pack exists and every live/preflight command is marked operator-only",
                False,
                False,
            )
        )
    if all_ticker_guard:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker live-scope guard",
                "locally_complete",
                "Guard exists and keeps all-ticker live authorization closed.",
                "already complete unless live-scope gates change",
                False,
                True,
            )
        )
    else:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker live-scope guard",
                "locally_buildable",
                "All-ticker live-scope guard has not been generated yet.",
                "guard exists and fails closed for open live flags/orders/learning/replication",
                False,
                False,
            )
        )
    if all_ticker_preflight:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker live-readonly preflight report",
                "locally_complete",
                "Readonly preflight pathway/report exists; actual Coinbase readonly evidence remains future ACK/operator dependent unless report shows attempted/pass.",
                "fresh readonly preflight passes for every included ticker and exact ACK exists",
                False,
                True,
            )
        )
    else:
        items.append(
            _item(
                "all-ticker workflow readiness",
                "all-ticker live-readonly preflight report",
                "locally_buildable",
                "All-ticker live-readonly preflight report/tool has not been generated yet.",
                "preflight report exists with live authorization still false",
                False,
                False,
            )
        )
    if shadow_params:
        items.append(
            _item(
                "shadow parameter approximation",
                "review-only parameter approximation pack",
                "locally_complete",
                "Shadow approximation exists and keeps parameter mutation closed.",
                "already complete unless evidence categories change",
                False,
                True,
            )
        )
    else:
        items.append(
            _item(
                "shadow parameter approximation",
                "review-only parameter approximation pack",
                "locally_buildable",
                "Shadow parameter approximation pack has not been generated yet.",
                "pack exists and parameter_change_allowed=false",
                False,
                False,
            )
        )
    if not shadow:
        items.append(
            _item(
                "shadow learning",
                "D6 shadow learning report",
                "locally_buildable",
                "The report-only shadow learning design has not been generated yet.",
                "d6-shadow-learning-report artifact exists and keeps execution bridge closed",
                False,
                False,
            )
        )
    if not checklist:
        items.append(
            _item(
                "regression/operator workflow",
                "operator 24h pre-run build checklist",
                "locally_buildable",
                "The final local pre-run build checklist has not been generated yet.",
                "operator-24h-prerun-build-checklist artifact exists and live_start_authorized=false",
                False,
                False,
            )
        )
    locally_buildable = [row for row in items if row["blocker_type"] == "locally_buildable"]
    locally_complete = [row for row in items if row["blocker_type"] == "locally_complete"]
    remaining_locally_buildable_count = len(locally_buildable)
    report = {
        "phase": PHASE_UNRESOLVED_BLOCKER_LEDGER,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "local_files_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "live_run_started": False,
        },
        "classification": "OK" if remaining_locally_buildable_count == 0 else "WATCH",
        "items": items,
        "categories": {
            "locally_complete": locally_complete,
            "locally_buildable_remaining": locally_buildable,
            "blocked_by_ACK": [row for row in items if row["blocker_type"] == "blocked_by_ACK"],
            "blocked_by_live_fresh_preflight": [row for row in items if row["blocker_type"] == "blocked_by_live_fresh_preflight"],
            "blocked_by_external_follower_repo": [row for row in items if row["blocker_type"] == "blocked_by_external_follower_repo"],
            "blocked_by_live_position_fill_evidence": [row for row in items if row["blocker_type"] == "blocked_by_live_position_fill_evidence"],
        },
        "governance_flags": {
            "unresolved_blocker_ledger_ready": True,
            "remaining_locally_buildable_item_count": remaining_locally_buildable_count,
            "all_remaining_items_are_ack_live_or_external_dependent": remaining_locally_buildable_count == 0,
            "live_start_authorized": False,
            "learning_to_execution_ready": False,
            "parameter_change_allowed": False,
        },
        "recommended_next_action": (
            "remaining steps are ACK/live/external-code dependent; prepare a BTC-USDC live-start decision pack only if operator explicitly asks"
            if remaining_locally_buildable_count == 0
            else "build remaining local report-only items before any live step"
        ),
    }
    return _json_safe(report)


def render_unresolved_blocker_ledger_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("governance_flags") or {}
    lines = [
        "# Unresolved Blocker Ledger",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Items", ""])
    for row in report.get("items") or []:
        lines.append(
            f"- {row.get('category')} / {row.get('item')}: blocker_type=`{row.get('blocker_type')}`, "
            f"blocks_BTC_24h=`{row.get('blocks_operator_started_BTC_USDC_24h_test')}`, "
            f"blocks_full_workflow=`{row.get('blocks_full_workflow')}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_UNRESOLVED_BLOCKER_LEDGER",
    "build_unresolved_blocker_ledger",
    "render_unresolved_blocker_ledger_markdown",
]
