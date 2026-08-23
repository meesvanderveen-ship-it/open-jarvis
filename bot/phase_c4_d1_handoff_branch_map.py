from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_c45_live_fill_pilot import C45_FILL_APPLY_ACK
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "c4_d1_handoff_branch_map_v1"
TARGET_TICKER = "BTC-USDC"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "learning_to_execution_enabled": False,
    }


def _read_text(root: Path, rel: str) -> str:
    path = root / rel
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json(root: Path, rel: str) -> Any:
    text = _read_text(root, rel)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _sha256(root: Path, rel: str) -> str:
    path = root / rel
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any) -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _orders(root: Path) -> List[Dict[str, Any]]:
    payload = _json(root, "state/open_orders.json")
    orders_obj = payload.get("orders", {}) if isinstance(payload, dict) else {}
    if isinstance(orders_obj, dict):
        return [row for row in orders_obj.values() if isinstance(row, dict)]
    if isinstance(orders_obj, list):
        return [row for row in orders_obj if isinstance(row, dict)]
    return []


def _positions(root: Path) -> Dict[str, Dict[str, Any]]:
    payload = _json(root, "state/positions.json")
    if not isinstance(payload, dict):
        return {}
    return {str(k): v for k, v in payload.items() if isinstance(v, dict)}


def _is_c4_entry_order(order: Dict[str, Any], ticker: str) -> bool:
    return (
        _normalize_ticker(order.get("ticker") or order.get("product_id")) == ticker
        and str(order.get("side") or "").upper() == "BUY"
        and str(order.get("mode") or "").lower() == "live"
        and str(order.get("execution_action") or "").lower() == "place_limit_buy"
        and (
            bool(order.get("opened_via_phase_c43"))
            or str(order.get("source_mode") or "").lower() == "autonomous_small_live"
            or str(order.get("client_order_id") or "").startswith("phasec-")
        )
    )


def _is_d3_exit_order(order: Dict[str, Any], ticker: str) -> bool:
    client_order_id = str(order.get("client_order_id") or "")
    return (
        _normalize_ticker(order.get("ticker") or order.get("product_id")) == ticker
        and str(order.get("side") or "").upper() == "SELL"
        and (
            client_order_id.startswith("phased3-")
            or str(order.get("source_mode") or "") == "phase_d3_live_exit"
            or "D3" in str(order.get("phase") or "").upper()
        )
    )


def _is_open_status(status: Any) -> bool:
    return str(status or "").lower() in {
        "planned",
        "pending",
        "submitted",
        "open",
        "partially_filled",
        "partial_fill",
        "cancel_pending",
        "replace_pending",
    }


def _is_fill_status(status: Any) -> bool:
    return str(status or "").lower() in {"filled", "done", "settled"}


def _is_partial_status(status: Any) -> bool:
    return str(status or "").lower() in {"partially_filled", "partial_fill"}


def _is_reject_status(status: Any) -> bool:
    return str(status or "").lower() in {"rejected", "submit_rejected", "failed"}


def _is_terminal_no_fill_status(status: Any) -> bool:
    return str(status or "").lower() in {"cancelled", "canceled", "expired", "invalidated"}


def _position_active(position: Dict[str, Any]) -> bool:
    return _to_decimal(position.get("position_size_base")) > 0 or _to_decimal(position.get("bot_managed_base")) > 0


def _order_already_linked_to_position(order: Dict[str, Any]) -> bool:
    return bool(
        order.get("position_created")
        or order.get("linked_position_id")
        or str(order.get("position_link_source") or "").strip()
    )


def _order_summary(orders: Iterable[Dict[str, Any]], ticker: str) -> Dict[str, Any]:
    all_orders = list(orders)
    c4_orders = [order for order in all_orders if _is_c4_entry_order(order, ticker)]
    open_c4 = [order for order in c4_orders if _is_open_status(order.get("status"))]
    d3_orders = [order for order in all_orders if _is_d3_exit_order(order, ticker)]
    open_d3 = [order for order in d3_orders if _is_open_status(order.get("status"))]
    return {
        "total_orders": len(all_orders),
        "c4_entry_order_count": len(c4_orders),
        "open_c4_entry_order_count": len(open_c4),
        "open_d3_exit_order_count": len(open_d3),
        "c4_status_counts": dict(Counter(str(order.get("status") or "unknown").lower() for order in c4_orders)),
        "c4_client_order_ids": [str(order.get("client_order_id") or "") for order in c4_orders[-5:]],
        "open_c4_client_order_ids": [str(order.get("client_order_id") or "") for order in open_c4],
        "open_d3_client_order_ids": [str(order.get("client_order_id") or "") for order in open_d3],
    }


def _current_branch(root: Path, ticker: str, *, include_terminal_c4_handoff: bool) -> Dict[str, Any]:
    orders = _orders(root)
    positions = _positions(root)
    btc_position = positions.get(ticker) or {}
    c4_orders = [order for order in orders if _is_c4_entry_order(order, ticker)]
    open_c4 = [order for order in c4_orders if _is_open_status(order.get("status"))]
    filled_c4 = [order for order in c4_orders if _is_fill_status(order.get("status"))]
    partial_c4 = [order for order in c4_orders if _is_partial_status(order.get("status"))]
    rejected_c4 = [order for order in c4_orders if _is_reject_status(order.get("status"))]
    terminal_no_fill_c4 = [order for order in c4_orders if _is_terminal_no_fill_status(order.get("status"))]
    open_d3 = [order for order in orders if _is_d3_exit_order(order, ticker) and _is_open_status(order.get("status"))]
    active_position = _position_active(btc_position)
    filled_needing_apply = [order for order in filled_c4 if not _order_already_linked_to_position(order)]

    reasons: List[str] = []
    branch_id = "A"
    status = "OK"
    title = "no_order_submitted"

    if len(open_c4) > 1:
        return {
            "branch_id": "G",
            "title": "inconsistent_evidence",
            "status": "STOP_NOW",
            "reasons": ["multiple_open_c4_entry_orders"],
        }
    if len(open_d3) > 0:
        return {
            "branch_id": "G",
            "title": "inconsistent_evidence",
            "status": "STOP_NOW",
            "reasons": ["unexpected_open_d3_exit_order"],
        }
    if not include_terminal_c4_handoff and not open_c4 and not active_position:
        return {
            "branch_id": "A",
            "title": "no_order_submitted",
            "status": "OK",
            "reasons": ["no_current_open_c4_order_or_active_btc_position_detected"],
        }
    if active_position and not filled_c4:
        return {
            "branch_id": "G",
            "title": "inconsistent_evidence",
            "status": "STOP_NOW",
            "reasons": ["active_btc_position_without_local_c4_fill_evidence"],
        }
    if open_c4:
        branch_id, title, status = "B", "order_submitted_still_open", "WATCH"
        reasons.append("one_open_c4_entry_order")
    elif partial_c4:
        branch_id, title, status = "E", "partial_fill_detected", "WATCH"
        reasons.append("partial_fill_requires_exact_c45_apply_ack_before_state_write")
    elif filled_c4 and active_position:
        branch_id, title, status = "F", "full_fill_already_applied_to_position_review_only", "WATCH"
        reasons.append("filled_order_and_active_position_require_d2_d3_preview_review")
    elif include_terminal_c4_handoff and filled_needing_apply:
        if active_position:
            branch_id, title, status = "F", "full_fill_already_applied_to_position_review_only", "WATCH"
            reasons.append("filled_order_and_active_position_require_d2_d3_preview_review")
        else:
            branch_id, title, status = "F", "full_fill_detected_apply_required", "WATCH"
            reasons.append("filled_order_requires_exact_c45_apply_ack_before_position_creation")
    elif rejected_c4:
        branch_id, title, status = "C", "order_rejected_or_submit_rejected", "WATCH"
        reasons.append("no_position_creation_from_reject")
    elif terminal_no_fill_c4:
        branch_id, title, status = "D", "order_cancelled_or_terminal_without_fill", "WATCH"
        reasons.append("no_position_creation_from_terminal_no_fill")
    else:
        reasons.append("no_open_or_terminal_c4_entry_order_detected")

    return {
        "branch_id": branch_id,
        "title": title,
        "status": status,
        "reasons": reasons,
    }


def _branch(
    *,
    branch_id: str,
    title: str,
    status: str,
    evidence_required: List[str],
    operator_next_step: str,
    allowed_actions: List[str],
    forbidden_actions: List[str],
    ack_required: List[str],
    monitor_or_post_run_evidence: List[str],
    notes: List[str],
) -> Dict[str, Any]:
    return {
        "branch_id": branch_id,
        "title": title,
        "classification": status,
        "evidence_required": evidence_required,
        "operator_next_step": operator_next_step,
        "allowed_actions_without_new_ack": allowed_actions,
        "forbidden_actions_without_separate_exact_ack": forbidden_actions,
        "ack_required_before_progression": ack_required,
        "monitor_or_post_run_evidence": monitor_or_post_run_evidence,
        "notes": notes,
    }


def _branches() -> List[Dict[str, Any]]:
    no_state_apply = ["no local fill apply", "no lifecycle apply", "no D2/D3 action", "no live exit"]
    live_forbidden = [
        "Coinbase submit",
        "Coinbase cancel",
        "Coinbase replace/reprice",
        "lifecycle apply",
        "local repair apply",
        "D3 live exit submit",
        "state mutation",
    ]
    return [
        _branch(
            branch_id="A",
            title="no_order_submitted",
            status="OK",
            evidence_required=[
                "monitor/post-run pack shows zero submitted/executed C4 entry orders in the run window",
                "state/open_orders.json has no open C4 BTC-USDC BUY",
                "state/positions.json has no active BTC-USDC bot-managed position from the run",
            ],
            operator_next_step="Archive evidence; no C4/D1 handoff is needed.",
            allowed_actions=["read-only monitor", "post-run evidence pack", "runbook review"],
            forbidden_actions=no_state_apply + live_forbidden,
            ack_required=[],
            monitor_or_post_run_evidence=["cycle executed count is zero", "open_orders=0", "open_d3_exit=0"],
            notes=["No order means there is no fill-to-position path to preview or apply."],
        ),
        _branch(
            branch_id="B",
            title="order_submitted_still_open",
            status="WATCH",
            evidence_required=[
                "exact BTC-USDC C4 client_order_id and exchange_order_id",
                "local open-order row status is submitted/open/partially_filled with no terminal snapshot",
                "monitor/post-run pack shows one open order and no non-BTC order",
            ],
            operator_next_step="Keep monitoring or request a separate read-only Coinbase poll later if local evidence is insufficient.",
            allowed_actions=["read-only monitor", "read-only post-run evidence pack", "operator-side Coinbase UI/export review"],
            forbidden_actions=["local fill apply", "position creation", "D2 plan apply/persist", "D3 live exit submit"] + live_forbidden,
            ack_required=["Coinbase read-only poll by Codex requires separate ACK if needed later"],
            monitor_or_post_run_evidence=["open_orders=1 maximum", "no applied lifecycle rows", "d2=0", "d3=0"],
            notes=["An open entry order is not a position. Do not build position actions from open-only evidence."],
        ),
        _branch(
            branch_id="C",
            title="order_rejected_or_submit_rejected",
            status="WATCH",
            evidence_required=[
                "submit response or lifecycle evidence with rejected/failed status",
                "no filled_size/fill summary",
                "local order row is terminal rejected or no accepted order row exists",
            ],
            operator_next_step="Inspect rejection cause and stop; a new entry attempt would require a separate future live-submit ACK.",
            allowed_actions=["read-only evidence review", "document rejection cause"],
            forbidden_actions=["position creation", "D1 fill apply", "D2 plan", "D3 preview from this order"] + live_forbidden,
            ack_required=["new live submit requires separate exact ACK"],
            monitor_or_post_run_evidence=["submit rejected/rejected reason in logs/order_events", "executed count remains zero"],
            notes=["A rejected submit cannot be treated as a no-fill position seed."],
        ),
        _branch(
            branch_id="D",
            title="order_cancelled_or_terminal_without_fill",
            status="WATCH",
            evidence_required=[
                "cancelled/expired/invalidated terminal evidence",
                "filled_size is zero and no fills summary exists",
                "local order row closed terminal without linked_position_id",
            ],
            operator_next_step="Archive terminal no-fill evidence; no D1 position transition is allowed.",
            allowed_actions=["read-only evidence review", "post-run evidence pack"],
            forbidden_actions=["position creation", "D1 fill apply", "D2 position plan", "D3 preview/live exit"] + live_forbidden,
            ack_required=["local terminal lifecycle apply requires separate exact ACK if local state is not already terminal"],
            monitor_or_post_run_evidence=["terminal no-fill order event", "open_orders returns 0 after terminal local state"],
            notes=["Terminal without fill ends the handoff. It does not authorize repair or a retry."],
        ),
        _branch(
            branch_id="E",
            title="partial_fill_detected",
            status="WATCH",
            evidence_required=[
                "Coinbase/UI/export or read-only snapshot showing partial fill",
                "exact filled_base, filled_quote, avg_fill_price and fee evidence",
                "matching local C4 order id and no duplicate local order",
                "state hashes before any apply",
            ],
            operator_next_step="Prepare fill-to-position preview only; local apply requires exact C4.5 ACK.",
            allowed_actions=["read-only fill evidence review", "fill-to-position preview without apply", "D2/D3 preview planning only after coherent applied/previewed position evidence"],
            forbidden_actions=["actual local fill apply without ACK", "lifecycle apply without ACK", "D3 live exit submit"] + live_forbidden,
            ack_required=[C45_FILL_APPLY_ACK, "separate lifecycle apply ACK if local terminal order mutation is required"],
            monitor_or_post_run_evidence=["post-run pack reports partial/fill-related C4 evidence", "d2/d3 counts must remain 0 unless explicitly previewed"],
            notes=["Partial fill must not be rounded into a full position without exact size/fee evidence."],
        ),
        _branch(
            branch_id="F",
            title="full_fill_detected",
            status="WATCH",
            evidence_required=[
                "Coinbase/UI/export or read-only snapshot showing FILLED",
                "exact filled_base, filled_quote, avg_fill_price, fees and settled evidence",
                "matching local C4 order row by client_order_id/exchange_order_id",
                "state hashes before any apply",
            ],
            operator_next_step="Run C4.5/D1 fill-to-position preview first; actual position creation requires exact C4.5 ACK. D2 plan and D3 preview remain non-live.",
            allowed_actions=["read-only fill evidence review", "fill-to-position preview", "D2 plan preview", "D3 preview with submit_live=False"],
            forbidden_actions=["local fill apply without ACK", "D3 live exit submit", "cancel/replace/reprice", "repair apply"] + live_forbidden,
            ack_required=[C45_FILL_APPLY_ACK, "separate future ACK for any D3 live exit submit"],
            monitor_or_post_run_evidence=["post-run pack reports one BTC-USDC fill only", "open_d3_exit=0", "live_exit_order_created=false"],
            notes=["D2/D3 preview is not permission to place a SELL. Live exits remain disabled until a future exact ACK."],
        ),
        _branch(
            branch_id="G",
            title="inconsistent_evidence",
            status="STOP_NOW",
            evidence_required=[
                "mismatched Coinbase/local order evidence, duplicate order evidence or unexpected state hash drift",
                "examples: exchange FILLED but local order missing, local open order with terminal exchange evidence, duplicate local C4 orders",
                "unexpected D2/D3 preview/apply rows or any live exit row",
            ],
            operator_next_step="Stop and collect evidence. Do not repair, lifecycle-apply, cancel, fill-reconcile or submit exits without a separate exact ACK.",
            allowed_actions=["read-only evidence collection", "operator-side screenshot/export collection"],
            forbidden_actions=["historical repair", "state edit", "fill apply", "lifecycle apply", "cancel/replace/reprice", "D3 live exit submit"] + live_forbidden,
            ack_required=[
                "separate exact ACK for any local repair apply",
                "separate exact ACK for lifecycle apply",
                "separate exact ACK for cancel/replace/reprice",
            ],
            monitor_or_post_run_evidence=["STOP_NOW monitor/post-run reasons", "before/after state hashes", "order_events and lifecycle hook rows"],
            notes=["Inconsistent evidence is a P0/P1 review stop, not an invitation to fix state manually."],
        ),
    ]


def build_c4_d1_handoff_branch_map(
    *,
    root: Path | str = ".",
    ticker: str = TARGET_TICKER,
    include_terminal_c4_handoff: bool = False,
) -> Dict[str, Any]:
    repo = Path(root)
    selected = _normalize_ticker(ticker) or TARGET_TICKER
    orders = _orders(repo)
    positions = _positions(repo)
    order_summary = _order_summary(orders, selected)
    current_branch = _current_branch(repo, selected, include_terminal_c4_handoff=include_terminal_c4_handoff)

    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "status": "c4_d1_handoff_branch_map_ready",
        "target_ticker": selected,
        "report_mode": "read_only_operator_branch_map",
        "include_terminal_c4_handoff": bool(include_terminal_c4_handoff),
        "current_state_evidence": {
            "state_hashes": {
                "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
                "state/positions.json": _sha256(repo, "state/positions.json"),
            },
            "order_summary": order_summary,
            "btc_position": {
                "position_size_base": str((positions.get(selected) or {}).get("position_size_base") or ""),
                "bot_managed_base": str((positions.get(selected) or {}).get("bot_managed_base") or ""),
                "reserved_base_open_exit_orders": str((positions.get(selected) or {}).get("reserved_base_open_exit_orders") or ""),
                "monitoring_enabled": (positions.get(selected) or {}).get("monitoring_enabled"),
            },
        },
        "current_branch": current_branch,
        "branches": _branches(),
        "ack_boundaries": {
            "fill_to_position_apply": C45_FILL_APPLY_ACK,
            "lifecycle_apply": "separate exact lifecycle apply ACK required",
            "local_repair": "separate exact local repair ACK required",
            "live_exit_submit": "separate exact D3 live exit submit ACK required",
            "cancel_replace_reprice": "separate exact order-id/action ACK required",
            "coinbase_read_only_poll": "separate ACK required if Codex is asked to poll Coinbase",
        },
        "tool_tie_ins": {
            "during_run_monitor": "python3 tools/show_btc_usdc_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC> --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> --baseline-positions-hash <PRE_START_POSITIONS_SHA256>",
            "post_run_evidence_pack": "python3 tools/build_btc_usdc_24h_post_run_evidence_pack.py --start-utc <OPERATOR_START_UTC> --stop-utc <OPERATOR_STOP_UTC> --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> --baseline-positions-hash <PRE_START_POSITIONS_SHA256> --json-out reports/live/btc-usdc-24h-evidence-<DATE>.json --markdown-out reports/live/btc-usdc-24h-evidence-<DATE>.md",
            "fill_preview_or_apply_tool": "tools/run_phase_c45_live_fill_pilot.py is the C4.5/D1 path; --apply-fill requires the exact C4.5 ACK and D3 preview is submit_live=False.",
        },
        "operator_conclusion": {
            "d2_d3_preview_is_not_live_exit_permission": True,
            "no_state_mutation_without_separate_exact_ack": True,
            "no_coinbase_call_from_this_report": True,
            "next_step_by_current_branch": current_branch.get("title"),
        },
        **_safety_flags(),
    }


def render_c4_d1_handoff_branch_map_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# C4/D1 Handoff Branch Map",
        "",
        "Read-only operator artifact. No Coinbase calls, no live action and no trading-state writes.",
        "",
        "## Summary",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- target_ticker: `{report.get('target_ticker')}`",
        f"- current_branch: `{(report.get('current_branch') or {}).get('branch_id')} - {(report.get('current_branch') or {}).get('title')}`",
        f"- current_classification: `{(report.get('current_branch') or {}).get('status')}`",
        f"- current_reasons: `{', '.join((report.get('current_branch') or {}).get('reasons') or [])}`",
        f"- open_c4_entry_order_count: `{((report.get('current_state_evidence') or {}).get('order_summary') or {}).get('open_c4_entry_order_count')}`",
        f"- open_d3_exit_order_count: `{((report.get('current_state_evidence') or {}).get('order_summary') or {}).get('open_d3_exit_order_count')}`",
        f"- state/open_orders.json: `{((report.get('current_state_evidence') or {}).get('state_hashes') or {}).get('state/open_orders.json')}`",
        f"- state/positions.json: `{((report.get('current_state_evidence') or {}).get('state_hashes') or {}).get('state/positions.json')}`",
        "",
        "## ACK Boundaries",
    ]
    for key, value in (report.get("ack_boundaries") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend([
        "",
        "D2/D3 preview is not live exit permission. A D3 preview must keep `submit_live=False` and does not authorize a SELL.",
        "",
        "## Branches",
    ])
    for branch in report.get("branches") or []:
        lines.extend([
            "",
            f"### Branch {branch.get('branch_id')} - {branch.get('title')}",
            f"- classification: `{branch.get('classification')}`",
            f"- operator_next_step: {branch.get('operator_next_step')}",
            f"- evidence_required: `{'; '.join(branch.get('evidence_required') or [])}`",
            f"- allowed_without_new_ack: `{'; '.join(branch.get('allowed_actions_without_new_ack') or [])}`",
            f"- forbidden_without_separate_exact_ack: `{'; '.join(branch.get('forbidden_actions_without_separate_exact_ack') or [])}`",
            f"- ack_required_before_progression: `{'; '.join(branch.get('ack_required_before_progression') or [])}`",
            f"- monitor_or_post_run_evidence: `{'; '.join(branch.get('monitor_or_post_run_evidence') or [])}`",
        ])
    lines.extend([
        "",
        "## Tool Tie-Ins",
    ])
    for key, value in (report.get("tool_tie_ins") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend([
        "",
        "## Conclusion",
        "- Evidence review, fill apply preview, actual local apply, D2 plan, D3 preview and D3 live exit submit are separate steps.",
        "- Actual fill-to-position apply, lifecycle apply, local repair, cancel/replace/reprice and live exits require separate exact ACKs.",
        "- This report is report-only and writes no trading state.",
    ])
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "TARGET_TICKER",
    "build_c4_d1_handoff_branch_map",
    "render_c4_d1_handoff_branch_map_markdown",
]
